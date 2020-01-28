# dupecheck
Check a directory (or set of directories) for duplicate files.

By default, a cache file (named `.dupecache`) is created in the current directory that stores information about scanned files to greatly reduce the time taken on subsequent scans. The cache can be moved with `--cache` or disabled entirely with `--no-cache`.

There is no special logic for hardlinks, and as such, hardlinks will be counted as duplicate files.

## Basic usage

`python3 dupecheck.py path`

See `--help` for a detailed explanation of each command-line argument.

## Exclude patterns

## Output parsing

The output is of the form

```
Dupe: "<path/to/first/file>" -> "<path/to/second/file>"
```

Therefore, a simple set of shell commands are sufficient to parse the output:

```
dupecheck.py <paths>
    | sed -e 's/^Dupe: //g' -e 's/ -> / /g'
    | while read a b; do echo -e "a:$a\nb:$b\n"; done
```
