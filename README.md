# dupecheck
Check a directory (or set of directories) for duplicate files.

By default, a cache file (named `.dupecache`) is created in the current directory that stores information about scanned files to greatly reduce the time taken on subsequent scans. The cache can be moved with `--cache` or disabled entirely with `--no-cache`.

There is no special logic for hardlinks, and as such, hardlinks will be counted as duplicate files.

## Basic usage

`python3 dupecheck.py path`

See `--help` for a detailed explanation of each command-line argument.

## Exclude patterns

This script provides various arguments for defining exclude rules. Each of these arguments can be used more than once. These arguments are as follows:

| -------- | -------- |
| `--x-dir NAME` | Exclude objects whose absolute path contains any directory named `NAME` |
| `--x-dir-glob GLOB` | Exclude objects whose absolute path contains any directory matching `GLOB` |
| `--x-path-glob GLOB` | Exclude objects whose absolute paths match `GLOB` |
| `--x-file NAME` | Exclude files named `NAME` |
| `--x-file-glob GLOB` | Exclude files with names matching `GLOB` |

By default (that is, unless `--no-default-exclude` is specified), the following exclude rules are assumed:

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
