# DDON-Translation 
This is a repository for data used to build translation patches for Dragon's Dogma Online.

This is a community project. Contributions welcome!

---

## 📑 Table of Contents
- [Contributing](#contributing)
- [How to Install Translations](#how-to-install-translations)
  - [English](#english)
  - [Portuguese Brazil](#portuguese_brazil)
  - [Spanish](#spanish)
  - [Viet](#viet)
  - [Traditional Chinese](#traditional-chinese)
  - [Simplified Chinese - WIP](#simplified-chinese)
- [Development](#development)
  - [How to generate gmd.csv](#how-to-generate-gmdcsv)
  - [Dependencies](#dependencies)
  - [How to generate the gmd manually](#how-to-generate-the-gmd-manually)
  - [generate_gmd.py -h](#generategmdpy--h)
- [External Credits](#external-credits)

---

## Contributing
If you would like to contribute to the translation effort, please [Join the development discord](https://discord.gg/Rvut5D8zGP).

## 📥 How to Install Translations

Download the `gmd.csv` file for your preferred language below:

### English
```plaintext
https://raw.githubusercontent.com/Sapphiratelaemara/DDON-translation/refs/heads/main/gmd.csv
```

### Portuguese Brazil
```plaintext
https://raw.githubusercontent.com/Sapphiratelaemara/DDON-translation/refs/heads/main/Portuguese%20(Brazil)/gmd.csv
```

### Spanish
```plaintext
https://raw.githubusercontent.com/Sapphiratelaemara/DDON-translation/refs/heads/main/Spanish/gmd.csv
```

### Traditional Chinese
```plaintext
https://raw.githubusercontent.com/Sapphiratelaemara/DDON-translation/refs/heads/main/Traditional%20Chinese/gmd.csv
```

### Simplified Chinese
🚧 Work in Progress (WIP)

### Viet
```plaintext
https://raw.githubusercontent.com/Sapphiratelaemara/DDON-translation/refs/heads/main/Viet/gmd.csv
```
## Development
### How to generate gmd.csv

Double click on the script `generate_gmd.bat`.

### dependencies

Install `python3` on your system to use the script `generate_gmd.py`.
> [!NOTE]
> If using Windows, if you type python and it is not installed, the windows store will popup, prompting you to install python.
> Close and reopen your terminal after it completes

### How to generate the gmd manually

Example command to generate `gmd.csv`
```plaintext
$ python generate_gmd.py "Fully Translated" splits
Generated gmd.csv
$ ls -l gmd.csv
-rw-r--r-- 1 USER 197121 24612262 Apr 20 21:43 gmd.csv
```

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