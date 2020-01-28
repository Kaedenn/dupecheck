# dupecheck.py
Check a directory (or set of directories) for duplicate files.

## Synopsis

```
usage: dupecheck.py [path...] [-p] [cache-arguments] [exclude-arguments]

positional arguments:
  path                  scan for duplicates in path (default: cwd)

optional arguments:
  -h, --help            show this help message and exit
  -d, --debug           show debugging information
  -p, --progress        show progress

cache arguments:
  --cache PATH          override cache file path (default: .dupecache)
  --no-cache            do not load or save a cache file

exclude arguments:
  -x DIR, --x-dir DIR   exclude objects in directories named DIR
  --x-dir-glob GLOB     exclude objects in directories matching GLOB
  --x-path-glob GLOB    exclude objects with paths matching GLOB
  --x-file FILE         exclude files named FILE
  --x-file-glob GLOB    exclude files matching GLOB
  --no-default-exclude  do not add default excludes

Default excludes are: "--x-dir .git", "--x-dir .svn"
```

Because `-p` (`--progress`) outputs to `stderr` after each file is processed, it is possible that this can slow down processing on systems with very fast file IO and/or very large cache files.

## Description

By default, a cache file (named `.dupecache`) is created in the current directory that stores information about scanned files to greatly reduce the time taken on subsequent scans. The cache can be moved with `--cache` or disabled entirely with `--no-cache`.

There is no special logic for hardlinks, and as such, hardlinks will be counted as duplicate files.

## Excludes

This script provides various arguments for defining exclude rules. Each of these arguments can be used more than once. These arguments are as follows.

| Argument | Description |
| -------- | -------- |
| `--x-dir NAME` | Exclude objects whose absolute path contains any directory named `NAME` |
| `--x-dir-glob GLOB` | Exclude objects whose absolute path contains any directory matching `GLOB` |
| `--x-path-glob GLOB` | Exclude objects whose absolute paths match `GLOB` |
| `--x-file NAME` | Exclude files named `NAME` |
| `--x-file-glob GLOB` | Exclude files with names matching `GLOB` |

By default (that is, unless `--no-default-exclude` is specified), the following exclude rules are assumed:

| Argument | Description |
| -------- | -------- |
| `--x-dir .git` | Exclude all objects within a `.git` directory, including descendants |
| `--x-dir .svn` | Exclude all objects within a `.svn` directory, including descendants |

## Output parsing

The output is of the form

```
Dupe: "<path/to/first/file>" -> "<path/to/second/file>"
```

Therefore, a simple set of shell commands are sufficient to parse the output:

```
dupecheck.py <paths> \
    | sed -e 's/^Dupe: //g' -e 's/"//g' \
    | awk -F' -> ' '{ print "1="$1"\n2="$2"\n"; }'
```

