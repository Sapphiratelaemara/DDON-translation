# DDON-Translation
This is a repository for data used to build translation patches for Dragon's Dogma Online.

This is a community project. Contributions welcome!

## Contributing
If you would like to contribute to the translation effort, please [Join the development discord](https://discord.gg/Rvut5D8zGP).

## How to generate gmd.csv

To generate the file `gmd.csv`, use the python script `generate_gmd.py`.

Example command to generate `gmd.csv`
```plaintext
$ python generate_gmd.py "Fully Translated" splits
Generated gmd.csv
$ ls -l gmd.csv
-rw-r--r-- 1 USER 197121 24612262 Apr 20 21:43 gmd.csv
```

### dependencies

Install python3 on your system to use the script `generate_gmd.py`.
> [!NOTE]
> If using Windows, if you type python and it is not installed, the windows store will popup, prompting you to install python.
> Close and reopen your terminal after it completes

### generate_gmd.py -h
```plaintext
usage: generate_gmd.py [-h] [-o OUTPUT_DIR] split_locations [split_locations ...]

positional arguments:
  split_locations       List of directories to find splits

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output_dir OUTPUT_DIR
                        Controls where gmd.csv will be written to
```

## External Credits

Many of the translations are taken from or adapted from the excellent work of other teams or people:
* [Dragon's Dogma Online Translations](http://ddonline.tumblr.com/) and their wiki [The White Dragon Temple](http://ddon.wikidot.com/). Their wiki is a great reference for playing DDON!
* [Julien-schu](http://julien-schu.tumblr.com/). Julien-schu's blog is a great resource for keeping up to date with news on DDON.
* [Feld](https://github.com/Feldherren) for writing toml2csv.py, something my brain was much too small for.
The current progress of this translation patch would not be where it is today without them!
