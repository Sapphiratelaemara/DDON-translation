

[![Translation Progress](https://img.shields.io/badge/Translation-Community%20Project-green)](#contributing) [![Discord](https://img.shields.io/badge/Join%20Discord-7289da?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/Rvut5D8zGP)

This is a data repository used to build translation patches for **Dragon's Dogma Online**. This project aims to create comprehensive translation patches to make the game accessible to players of different languages around the world. It is a community-driven project, and contributions are welcome!

## 📋 Summary

- [📥 How to Install Translations](#-how-to-install-translations)
- [🚀 Development](#-development)
  - [📋 Prerequisites](#-prerequisites)
  - [⚙️ Generating the gmd.csv](#-generating-the-gmdcsv)
  - [🖱️ Simple Method (Windows)](#-simple-method-windows)
  - [💻 Manual Method (Command Line)](#-manual-method-command-line)
- [🛠️ Available Tools](#-available-tools)
  - [🧹 Cleaning Tools](#-cleaning-tools)
  - [✅ Validation Tools](#-validation-tools)
  - [🔧 Processing Tools](#-processing-tools)
- [🌍 Supported Languages](#-supported-languages)
- [🤝 How to Contribute](#-how-to-contribute)
- [🐛 Troubleshooting](#-troubleshooting)
- [👥 External Credits](#-external-credits)
- [📜 License](#-license)

## 📥 How to Install Translations

- Open the game launcher and click the marked button; a new window will open.
- <img width="143" height="158" alt="image" src="https://github.com/user-attachments/assets/76e283fb-739c-442c-8e27-1f4a6030d36b" />

- Copy the link to the `gmd.csv` according to your language from the links below.
- Paste your link into the window that opened, and click OK.
- Another window will appear; select Japanese as the original and choose English for any other language.
- Click OK and wait for the update.  
- Repeat the process if any issues appear.

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

### Korean (한국어)
Korean needs a modified font (Hangul glyphs are drawn into unused kanji slots), so it is installed as a **launcher mod** instead of the CSV link above.

1. Download [`Korean/DDON_Korean_launcher_mod.zip`](https://github.com/Sapphiratelaemara/DDON-translation/raw/refs/heads/main/Korean/DDON_Korean_launcher_mod.zip).
2. In the launcher, open **Mod Installation** and select the zip.
3. Wait until "Mod installed" appears.

The mod applies `Korean/gmd.csv` (`packGmd`) and replaces the font in `ui/gui_cmn.arc` and two menu header textures in `ddo_common.arc`. To remove it, restore the original game files.


## 🚀 Development

### 📋 Prerequisites

- **Python 3.7+** installed on your system
- **Git** to clone the repository
- Text/Code editor or spreadsheet software to edit CSV files


### ⚙️ Generating the gmd.csv (Currently only used for English)

#### 🖱️ Simple Method (Windows)

1. Double-click the `generate_gmd.bat` file.
2. Wait for the processing to complete.
3. The `gmd.csv` file will be generated automatically.

#### 💻 Manual Method (Command Line)

```plaintext
# Generate gmd.csv using default directories
$ python generate_gmd.py "Fully Translated" splits
Generated gmd.csv

# Check the generated file
$ ls -l gmd.csv
-rw-r--r-- 1 USER 197121 24612262 Apr 20 21:43 gmd.csv
```

##### View script options and help:
```plaintext
usage: generate_gmd.py [-h] [-o OUTPUT_DIR] split_locations [split_locations ...]

positional arguments:
  split_locations       List of directories to find splits

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output_dir OUTPUT_DIR
                        Controls where gmd.csv will be written to
```

## 🛠️ Available Tools
(Note that these tools have been made when required, to the best of the ability of the writer; expect possible problems.
Fixes and improvements by knowledgeable people would be very welcome!)
### 🧹 Cleaning Tools

| Script | Description |
|--------|------------|
| `Forbidden characters replacer.py` | Removes forbidden characters |
| `Newline remover.py` | Removes unnecessary line breaks |
| `Duplicate remover.py` | Removes duplicate entries |
| `csv header scrubber.py` | Cleans CSV headers |


### ✅ Validation Tools

| Script | Description |
|--------|------------|
| `check_tag_limiters.py` | Checks tag delimiters |
| `check_lengths.py` | Checks string lengths |
| `Tag Typo Checker.py` | Detects typos in tags |
| `mismatch.py` | Finds mismatches |

### 🔧 Processing Tools

| Script | Description |
|--------|------------|
| `SpeakerFiller.py` | Fills speaker information |
| `toml2csv.py` | Converts TOML files to CSV |
| `linebreaker.py` | Adds line breaks (Old and mostly deprecated, does not correctly handle tags) |
| `Tag Fixer.py` | Fixes malformed tags |


## 🌍 Supported Languages

| Language | Status | Main File |
|----------|--------|-----------|
| 🇺🇸 English | 🔄 WIP | `gmd.csv` |
| 🇧🇷 Portuguese (Brazil) | 🔄 WIP | `Portuguese (Brazil)/gmd.csv` |
| 🇪🇸 Spanish | 🔄 WIP | `Spanish/gmd.csv` |
| 🇨🇳 Simplified Chinese | 🔄 WIP | `Simplified Chinese/` |
| 🇹🇼 Traditional Chinese | 🔄 WIP | `Traditional Chinese/gmd.csv` |
| 🇻🇳 Vietnamese | 🔄 WIP | `Viet/gmd.csv` |
| 🇰🇷 Korean | 🔄 WIP | `Korean/gmd.csv` + `Korean/DDON_Korean_launcher_mod.zip` |


## 🤝 How to Contribute

To contribute to the translation effort, join the development Discord:

[![Discord](https://img.shields.io/badge/Join%20Discord-7289da?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/Rvut5D8zGP)


### 📝 Translation Guidelines

1. **Game Context**: Keep terms specific to Dragon's Dogma.
2. **Consistency**: Use the available glossary to maintain consistent translations.
3. **Formatting**: Preserve HTML/XML tags and special formatting.
4. **Quality**: Prioritize clarity and naturalness in the target language.


### 🔍 Review Process

1. Edit the relevant CSV files in the languages folder/subfolders.
1a. If editing English: make edits in the subfolders, as the english gmd is generated from those files. 
2. Run the validation tools.
3. Test the changes in the game.
4. Submit a Pull Request.
5. Wait for community review.

## 🐛 Troubleshooting

### ❌ Common Issues

**Python not found (Windows):**
1. Install Python via the Microsoft Store.
2. Restart the terminal.
3. Test with `python --version`.

**Malformed tags:**
```plaintext
# Run the tag checker
python Tools/check_tag_limiters.py "Fully Translated/*.csv"
```
### 🔍 Debug Logs

The scripts generate logs in:
- `Tools/results.txt` - Processing log
- `Tools/invalid_tags.txt` - Detected invalid tags
- `Tools/problematic_tag_limiters.txt` - Tag delimiter issues

## 👥 External Credits

Many of the translations are based on or adapted from the excellent work of other teams:

### 🌟 Main Contributors

- **[Dragon's Dogma Online Translations](http://ddonline.tumblr.com/)** and their wiki **[The White Dragon Temple](http://ddon.wikidot.com/)**
  - Excellent reference for playing DDON
- **[Julien-schu](http://julien-schu.tumblr.com/)**
  - Great resource for DDON news
- **[Feld](https://github.com/Feldherren)**
  - Creator of `toml2csv.py`

### 🙏 Acknowledgements

The current progress of this translation patch would not be possible without the dedicated work of the community!

## 📜 License

This project is a community-driven effort focused on the preservation and accessibility of Dragon's Dogma Online.

---

<div align="center">

### Made with ❤️ by the Dragon's Dogma Online Community

</div>

