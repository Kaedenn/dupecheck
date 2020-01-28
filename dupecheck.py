#!/usr/bin/env python3

"""
Check for duplicate files within the given directory tree. By default, the
current directory is scanned.

For faster subsequent executions, a cache file is generated in the current
directory with a summary of the scanned files. The cache file's path can be
changed via the --cache argument, or disabled via the --no-cache argument
(which just sets the cache file to os.devnull).

The following exclude rules are available. These can be used more than once:
  --x-dir NAME          Exclude objects within one of the named directories.
  --x-dir-glob GLOB     Exclude objects within directories matching GLOB.
  --x-path-glob GLOB    Exclude objects with paths matching GLOB.
  --x-file NAME         Exclude files having one of the names given.
  --x-file-glob GLOB    Exclude files matching GLOB.

By default, the following exclude rule is provided:
  --x-dir .git          Exclude objects within the ".git" directory.
  --x-dir .svn          Exclude objects within the ".svn" directory.
This can be overruled via the --no-default-exclude argument.

There is no special logic for hardlinks. Symbolic links are completely ignored.
"""

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import struct
import sys
import termios
import time

CACHE_NAME = ".dupecache"

COMPARE_SAMEFILE = 1
COMPARE_DIFFERENT = 0
COMPARE_DUPLICATE = -1

class Progress(object):
  """
  Display progress information
  """

  @classmethod
  def get_term_file_object(klass):
    return open(os.ctermid())

  @classmethod
  def get_output_file_object(klass):
    return sys.stderr

  @classmethod
  def get_cols(klass, f):
    size_arg = struct.pack("HHHH", 0, 0, 0, 0)
    size_packed = fcntl.ioctl(f, termios.TIOCGWINSZ, size_arg)
    nr, nc, xpx, ypx = struct.unpack("HHHH", size_packed)
    return nc - 1

  def __init__(self, fobj=None, cols=None):
    self._fobj = fobj
    self._cols = cols
    self._len = 0
    if cols is None:
      if fobj is None:
        termfobj = Progress.get_term_file_object()
      else:
        termfobj = fobj
      self._cols = Progress.get_cols(termfobj)
    if fobj is None:
      self._fobj = Progress.get_output_file_object()

  def clear_line(self):
    "Clear the line of any leftover text"
    self._fobj.write(" "*self._len)
    self._fobj.write("\r")

  def log(self, message):
    "Log the message to the file object specified in the constructor"
    part = message[:self._cols]
    if len(part) < self._len:
      part = (part + " " * (self._len - len(part)))[:self._cols]
    self._fobj.write(part)
    self._fobj.write("\r")
    self._len = min(max(self._len, len(message)), self._cols)

  def __call__(self, message):
    "Convenience wrapper for self.log(message)"
    return self.log(message)

def is_str(val):
  "Python 2 and 3 isinstance(val, basestring) drop-in"
  try:
    basestring
    return isinstance(val, basestring)
  except NameError:
    return isinstance(val, str)

def debug(msg):
  "Print a simple debug message"
  sys.stderr.write("DEBUG: {}\n".format(msg))

def mtime_key(p):
  "Provide sorting key on the path's modification time"
  return os.stat(p).st_mtime

def file_info(path):
  "Return (inode, size, mtime) for path"
  s = os.stat(path)
  return (s.st_ino, s.st_size, s.st_mtime)

def file_hash(path):
  "Obtain the hash of a file"
  return hashlib.sha1(open(path, "rb").read()).hexdigest()

def json_load(path_or_fobj):
  "Attempt to load a JSON object from path"
  if is_str(path_or_fobj):
    fobj = open(path_or_fobj)
  else:
    fobj = path_or_fobj
  json_str = fobj.read()
  if len(json_str) > 0:
    return json.loads(json_str)
  return {}

class ExcludeList(object):
  "Test if a path satisfies an elaborate set of exclude rules"
  def __init__(self):
    self._files = []
    self._file_globs = []
    self._path_globs = []
    self._dirs = []
    self._dir_globs = []

  def add_file(self, f):
    self._files.append(f)

  def add_file_glob(self, f):
    self._file_globs.append(f)

  def add_path(self, p):
    self._path_globs.append(p)

  def add_dir(self, d):
    self._dirs.append(d)

  def add_dir_glob(self, d):
    self._dir_globs.append(d)

  def test(self, path):
    "Return True if path matches exclude list, False otherwise"
    base = os.path.basename(path)
    drive, dpath = os.path.splitdrive(path)
    dparts = path.split(os.sep)
    if base in self._files:
      return True
    if any(fnmatch.fnmatch(base, g) for g in self._file_globs):
      return True
    if any(fnmatch.fnmatch(path, g) for g in self._path_globs):
      return True
    for p in dparts:
      if p in self._dirs:
        return True
      if any(fnmatch.fnmatch(p, g) for g in self._dir_globs):
        return True
    return False

class CachedFileList(object):
  """
  Helper class for finding duplicate files, using a cache of known files.
  """
  def __init__(self, cache_path=None, exclude=None, **kwargs):
    if cache_path is not None:
      self._cache_path = cache_path
    else:
      self._cache_path = os.path.join(os.path.dirname(sys.argv[0]), CACHE_NAME)
    self._exclude = () if exclude is None else exclude
    self._files_by_path = {}
    self._files_by_hash = {}
    self._empty_files = []
    self._bytes_read = 0
    self._files_scanned = 0
    self._start_time = time.time()
    self.load()

  def _sanitize(self, path):
    if os.path.isabs(path):
      return path
    return os.path.relpath(path, os.path.dirname(self._cache_path))

  def load(self):
    try:
      cache = json_load(open(self._cache_path))
      debug("Opened cache file {}".format(self._cache_path))
      for path, info in cache.get("files_by_path", {}).items():
        spath = self._sanitize(path)
        self._files_by_path[spath] = info
        self._files_by_hash[info["hash"]] = cache["files_by_hash"][info["hash"]]
        self._files_by_hash[info["hash"]]["path"] = spath
      debug("Loaded cache: {} files by path, {} files by hash".format(len(self._files_by_path), len(self._files_by_hash)))
      self._purge_old()
    except IOError as e:
      self._files = {}

  def save(self):
    cache = {}
    cache["files_by_path"] = self._files_by_path
    cache["files_by_hash"] = self._files_by_hash
    json.dump(cache, open(self._cache_path, "w"))
    debug("Writing cache: {} files by path, {} files by hash".format(len(self._files_by_path), len(self._files_by_hash)))
    debug("Saved cache to {}".format(self._cache_path))

  def stats(self):
    stats = {
      "bytes": self._bytes_read,
      "files": self._files_scanned,
      "bytes_per_second": self._bytes_read / (time.time() - self._start_time)
    }
    return stats

  def _purge_old(self):
    # Purge old entries from the cache that no longer exist
    paths_to_remove = []
    for path in self._files_by_path:
      if not os.path.exists(path):
        paths_to_remove.append(path)
      elif os.stat(path).st_size == 0:
        paths_to_remove.append(path)
    for path in paths_to_remove:
      filehash = self._files_by_path[path]["hash"]
      if path in self._files_by_path:
        del self._files_by_path[path]
      if filehash in self._files_by_hash:
        del self._files_by_hash[filehash]

  def _check_duplicate(self, path):
    # Path is already sanitized
    inode, size, mtime = file_info(path)
    filehash = file_hash(path)
    if filehash in self._files_by_hash:
      if not os.path.samefile(path, self._files_by_hash[filehash]["path"]):
        return COMPARE_DUPLICATE, self._files_by_hash[filehash]["path"]
    return COMPARE_DIFFERENT, None

  def _should_add_file(self, path):
    if path in self._files_by_path:
      inode, size, mtime = file_info(path)
      if inode == self._files_by_path[path]["inode"]:
        if size > 0 and size == self._files_by_path[path]["size"]:
          if mtime == self._files_by_path[path]["mtime"]:
            return False
    return True

  def _add_file(self, path):
    # Path is already sanitized by this point
    debug("Adding file {}".format(path))
    inode, size, mtime = file_info(path)
    filehash = file_hash(path)
    self._bytes_read += size
    bypath = {
      "inode": inode,
      "size": size,
      "mtime": mtime,
      "hash": filehash
    }
    byhash = {
      "path": path,
      "inode": inode,
      "size": size,
      "mtime": mtime
    }
    self._files_by_path[path] = bypath
    self._files_by_hash[filehash] = byhash

  def try_add_entry(self, path):
    debug("Examining {!r}...".format(path))
    self._files_scanned += 1
    path = self._sanitize(path)
    if path in self._files_by_path:
      # Constraint: paths cannot be duplicated; overwrite if file differs
      if self._should_add_file(path):
        self._add_file(path)
        return COMPARE_DIFFERENT, None
      else:
        return COMPARE_SAMEFILE, path
    else:
      result, otherpath = self._check_duplicate(path)
      if result == COMPARE_DIFFERENT:
        self._add_file(path)
        return COMPARE_DIFFERENT, None
      else:
        # Different path but not COMPARE_DIFFERENT -> duplicate
        return COMPARE_DUPLICATE, otherpath

def walk_trees(*paths, **kwargs):
  """Recursively walk paths and yield every file within (omitting directories).
  Keyword arguments:
    exclude_conf    exclude configuration (or None)
  """
  exclude_conf = kwargs.get("exclude_conf")
  debug("walk_trees {!r} (kwargs={})".format(paths, kwargs))
  for root in paths:
    for r, dirs, files in os.walk(root):
      for f in files:
        p = os.path.join(r, f)
        if os.path.islink(p):
          continue
        if exclude_conf is not None and exclude_conf.test(p):
          continue
        yield p

def cached_dupecheck_multi(roots, cache_path=None, exclude_conf=None, **kwargs):
  """
  Check roots for duplicates.
  """
  cache = CachedFileList(cache_path=cache_path, **kwargs)
  dupes = []
  i = 1
  num_items = len(tuple(walk_trees(*roots, exclude_conf=exclude_conf)))
  debug("Scanning {} items".format(num_items))
  for fpath in walk_trees(*roots, exclude_conf=exclude_conf):
    stats = cache.stats()
    debug_msg = "Scanning {}/{} {} ({} B/S)".format(i, num_items, fpath, stats["bytes_per_second"])
    if kwargs.get("progress"):
      kwargs["progress"](debug_msg)
    else:
      debug(debug_msg)
    status, path = cache.try_add_entry(fpath)
    if status == COMPARE_DUPLICATE:
      dupes.append((fpath, path))
    i += 1
  if kwargs.get("progress"):
    kwargs["progress"].clear_line()
  cache.save()
  return dupes

def cached_dupecheck(root, cache_path=None, exclude_conf=None, **kwargs):
  """
  Check root for duplicates.
  """
  return cached_dupecheck_multi((root,), cache_path=cache_path, exclude_conf=exclude_conf, **kwargs)

def _parse_args():
  ap = argparse.ArgumentParser(epilog="""
Default excludes are: "--x-dir .git", "--x-dir .svn" """)
  ap.add_argument("path", nargs="*", default=os.getcwd(), help="scan for duplicates in path (default: cwd)")
  ap.add_argument("-d", "--debug", action="store_true", help="show debugging information")
  ap.add_argument("-p", "--progress", action="store_true", help="show progress (may slow down scanning on systems with very fast disk IO)")
  ap.add_argument("--cache", metavar="PATH", default=CACHE_NAME, help="override cache file path (default: %(default)s)")
  ap.add_argument("--no-cache", action="store_true", help="do not load or save a cache file")
  ap.add_argument("-x", "--x-dir", metavar="DIR", action="append", help="exclude objects in directories named DIR")
  ap.add_argument("--x-dir-glob", metavar="GLOB", action="append", help="exclude objects in directories matching GLOB")
  ap.add_argument("--x-path-glob", metavar="GLOB", action="append", help="exclude objects with paths matching GLOB")
  ap.add_argument("--x-file", metavar="FILE", action="append", help="exclude files named FILE")
  ap.add_argument("--x-file-glob", metavar="GLOB", action="append", help="exclude files matching GLOB")
  ap.add_argument("--no-default-exclude", action="store_true", help="do not add default excludes")
  args = ap.parse_args()
  opts = {
    "paths": [],
    "progress": None,
    "cache_path": os.devnull if args.no_cache else args.cache,
    "debug": args.debug,
  }
  if opts["cache_path"] is not None:
    if os.path.isdir(opts["cache_path"]):
      opts["cache_path"] = os.path.join(opts["cache_path"], CACHE_NAME)
    elif opts["cache_path"] == CACHE_NAME:
      opts["cache_path"] = os.path.join(os.getcwd(), CACHE_NAME)
  if is_str(args.path):
    opts["paths"].append(os.path.realpath(args.path))
  else:
    opts["paths"].extend(os.path.realpath(p) for p in args.path)
  opts["cache_path"] = os.path.realpath(opts["cache_path"])
  if args.progress:
    opts["progress"] = Progress()

  each_none = lambda o: () if o is None else iter(o)
  exclude_conf = ExcludeList()
  for i in each_none(args.x_dir):
    exclude_conf.add_dir(i)
  for i in each_none(args.x_dir_glob):
    exclude_conf.add_dir_glob(i)
  for i in each_none(args.x_path_glob):
    exclude_conf.add_path_glob(i)
  for i in each_none(args.x_file):
    exclude_conf.add_file(i)
  for i in each_none(args.x_file_glob):
    exclude_conf.add_file_glob(i)
  if not args.no_default_exclude:
    exclude_conf.add_dir_glob(".git")
    exclude_conf.add_dir_glob(".svn")
  opts["exclude_conf"] = exclude_conf
  return opts

if __name__ == "__main__":
  opts = _parse_args()
  roots = opts["paths"]
  if not opts["debug"]:
    debug = lambda msg: None
  debug("Processed arguments: {}".format(opts))
  empty = set()
  for path, dupepath in sorted(cached_dupecheck_multi(roots, **opts)):
    p1, p2 = sorted((path, dupepath), key=mtime_key)
    if os.path.isfile(p1) and os.stat(p1).st_size == 0:
      empty.add(p1)
      empty.add(p2)
      continue
    print("Dupe: \"{}\" -> \"{}\"".format(os.path.realpath(p1), os.path.realpath(p2)))
    if file_hash(path) != file_hash(dupepath):
      print("ERROR!!! {} and {} have different hashes".format(path, dupepath))
  if len(empty) > 0:
    print("Empty files:")
    print("\n".join(sorted(empty)))

# vim: ts=2:sts=2:sw=2
