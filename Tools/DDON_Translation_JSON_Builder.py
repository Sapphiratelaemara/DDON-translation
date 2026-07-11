import csv
import json
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict


# --------------------------------------------------
# File dialogs
# --------------------------------------------------

def browse_file(entry):
    path = filedialog.askopenfilename()

    if path:
        entry.delete(0, tk.END)
        entry.insert(0, path)



def browse_save(entry):
    path = filedialog.asksaveasfilename(
        defaultextension=".json"
    )

    if path:
        entry.delete(0, tk.END)
        entry.insert(0, path)



# --------------------------------------------------
# Logging
# --------------------------------------------------

def write_log(text):

    log_box.insert(
        tk.END,
        text + "\n"
    )

    log_box.see(tk.END)
    root.update()



# --------------------------------------------------
# Text normalization
# --------------------------------------------------

def normalize_text(text):

    if not text:
        return ""

    text = text.lower().strip()

    # Remove level/rank markers
    text = re.sub(
        r"\s*(lv|lvl|level)\.?\s*\d+",
        "",
        text,
        flags=re.IGNORECASE
    )

    # Normalize apostrophes
    text = text.replace(
        "’",
        "'"
    )

    # Remove bracketed suffixes
    text = re.sub(
        r"[\(\[\{【].*?[\)\]\}】]",
        "",
        text
    )

    # Remove upgrade arrows
    text = re.sub(
        r"[↑↓]",
        "",
        text
    )

    # Remove trailing upgrade numbers
    text = re.sub(
        r"\s*\+?\d+$",
        "",
        text
    )

    # Remove plus symbols
    text = text.replace(
        "+",
        ""
    )

    # Remove punctuation
    text = re.sub(
        r"[^\w\s]",
        "",
        text
    )

    # Collapse spaces
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()

def normalize_japanese(text):

    if not text:
        return ""

    # Remove trailing numbers
    # 物理攻撃低下＋5 -> 物理攻撃低下＋
    text = re.sub(
        r"\d+$",
        "",
        text
    )

    # Remove trailing + symbols
    # 物理攻撃低下＋ -> 物理攻撃低下
    text = re.sub(
        r"[＋+]+$",
        "",
        text
    )

    return text.strip()

def normalize_text_variant(text):

    if not text:
        return ""

    text = re.sub(
        r"\s*(lv|lvl|level)\.?\s*\d+",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*\+?\d+$",
        "",
        text
    )

    text = re.sub(
        r"[＋+]+$",
        "",
        text
    )

    return text.strip()

# --------------------------------------------------
# Find CSV matches
# --------------------------------------------------

def find_csv_match(target, csv_entries):

    # 1. Exact match
    if target in csv_entries:
        return (
            csv_entries[target],
            "Exact"
        )


    # 2. Normalized match
    normalized_target = normalize_text(target)

    for text, entries in csv_entries.items():

        if normalize_text(text) == normalized_target:

            normalized_entries = []

            for entry in entries:

                cleaned = entry.copy()

                # Only normalize output because this was
                # a normalized match
                cleaned["MsgJp"] = normalize_japanese(
                    cleaned["MsgJp"]
                )

                normalized_entries.append(
                    cleaned
                )

            return (
                normalized_entries,
                "Normalized"
            )


    return (
        [],
        "Missing"
    )



# --------------------------------------------------
# Generate mapping.json
# --------------------------------------------------

def generate_mapping():

    json_file = mapping_json.get()

    csv_file = mapping_csv.get()

    output_file = mapping_output.get()



    if not all(
        [
            json_file,
            csv_file,
            output_file
        ]
    ):

        messagebox.showerror(
            "Error",
            "Select all files."
        )

        return



    try:


        write_log(
            "Loading en-US.json..."
        )


        with open(
            json_file,
            "r",
            encoding="utf-8"
        ) as f:

            english_json = json.load(f)



        translations = (
            english_json
            .get(
                "translations",
                {}
            )
        )


        write_log(
            f"JSON entries: {len(translations)}"
        )



        write_log(
            "Reading master CSV..."
        )



        csv_entries = defaultdict(list)



        with open(
            csv_file,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:


            reader = csv.DictReader(f)


            for row in reader:


                english = row.get(
                    "MsgEn",
                    ""
                )


                if not english:
                    continue



                csv_entries[english].append(
                    {
                        "MsgJp": row.get(
                            "MsgJp",
                            ""
                        ),

                        "GmdPath": row.get(
                            "GmdPath",
                            ""
                        ),

                        "ArcName": row.get(
                            "ArcName",
                            ""
                        ),

                        "ReadIndex": str(
                            row.get(
                                "ReadIndex",
                                ""
                            )
                        )
                    }
                )



        write_log(
            f"CSV unique strings: {len(csv_entries)}"
        )



        mapping = {}

        exact = 0

        normalized = 0

        missing = 0



        write_log(
            "Matching entries..."
        )



        for key, english_text in translations.items():


            matches, match_type = find_csv_match(
                english_text,
                csv_entries
            )



            if matches:


                mapping[key] = {

                    "English": english_text,

                    "MatchType": match_type,

                    "Locations": matches

                }


                if match_type == "Exact":
                    exact += 1

                else:
                    normalized += 1



            else:

                missing += 1



        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                mapping,
                f,
                indent=4,
                ensure_ascii=False
            )



        write_log("")
        write_log(
            "Mapping complete."
        )

        write_log(
            f"Exact matches: {exact}"
        )

        write_log(
            f"Normalized matches: {normalized}"
        )

        write_log(
            f"Missing: {missing}"
        )



    except Exception as e:

        messagebox.showerror(
            "Error",
            str(e)
        )
# --------------------------------------------------
# Build JSON
# --------------------------------------------------

def build_json():

    mapping_file = build_mapping.get()

    source_file = build_source_json.get()

    output_file = build_output.get()

    mode = build_mode.get()

    locale = build_locale.get()



    if not all(
        [
            mapping_file,
            source_file,
            output_file
        ]
    ):

        messagebox.showerror(
            "Error",
            "Select required files."
        )

        return



    try:

        write_log(
            "Loading mapping..."
        )


        with open(
            mapping_file,
            "r",
            encoding="utf-8"
        ) as f:

            mapping = json.load(f)



        write_log(
            "Loading source JSON..."
        )


        with open(
            source_file,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)



        replacements = {}



        # ------------------------------------------
        # Japanese generation
        # ------------------------------------------

        if mode == "Japanese":

            write_log(
                "Using MsgJp..."
            )


            for key, entry in mapping.items():

                locations = entry.get(
                    "Locations",
                    []
                )


                for location in locations:

                    japanese = location.get(
                        "MsgJp",
                        ""
                    )


                    if japanese:

                        replacements[key] = japanese

                        break



        # ------------------------------------------
        # Other language generation
        # ------------------------------------------

        else:

            csv_file = build_language_csv.get()

            column = translation_column.get()



            if not csv_file:

                messagebox.showerror(
                    "Error",
                    "Select translation CSV."
                )

                return



            write_log(
                "Loading translation CSV..."
            )



            translated_locations = {}



            with open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as f:


                reader = csv.DictReader(f)



                for row in reader:


                    identifier = (

                        row.get(
                            "GmdPath",
                            ""
                        ),

                        row.get(
                            "ArcName",
                            ""
                        ),

                        str(
                            row.get(
                                "ReadIndex",
                                ""
                            )
                        )
                    )


                    translated_locations[identifier] = row.get(
                        column,
                        ""
                    )



            write_log(
                "Matching translation locations..."
            )



            for key, entry in mapping.items():

                locations = entry.get(
                    "Locations",
                    []
                )


                for location in locations:

                    identifier = (

                        location.get(
                            "GmdPath",
                            ""
                        ),

                        location.get(
                            "ArcName",
                            ""
                        ),

                        str(
                            location.get(
                                "ReadIndex",
                                ""
                            )
                        )
                    )


                    if identifier in translated_locations:

                        translated_text = translated_locations[
                            identifier
                        ]


                        # Only remove suffixes when the
                        # English match was normalized.
                        # Exact matches remain untouched.
                        if entry.get(
                            "MatchType"
                        ) == "Normalized":

                            translated_text = normalize_text_variant(
                                translated_text
                            )


                        replacements[key] = translated_text

                        break



        write_log(
            f"Replacement entries: {len(replacements)}"
        )



        # ------------------------------------------
        # Apply replacements
        # ------------------------------------------

        translated = 0

        missing = []



        translations = data.get(
            "translations",
            {}
        )



        for key in translations:

            if key in replacements:

                translations[key] = replacements[key]

                translated += 1

            else:

                missing.append(key)



        if locale:

            data["locale"] = locale



        write_log(
            "Saving output..."
        )



        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )



        if missing:

            report_file = (
                output_file +
                "_missing.txt"
            )


            with open(
                report_file,
                "w",
                encoding="utf-8"
            ) as f:

                for key in missing:

                    f.write(
                        key +
                        "\n"
                    )


            write_log(
                f"Missing report: {report_file}"
            )



        write_log("")
        write_log(
            "Completed."
        )

        write_log(
            f"Translated: {translated}"
        )



    except Exception as e:

        messagebox.showerror(
            "Error",
            str(e)
        )
# --------------------------------------------------
# GUI helpers
# --------------------------------------------------

def add_file_row(
    parent,
    label,
    variable,
    save=False
):

    frame = ttk.Frame(parent)

    frame.pack(
        fill="x",
        padx=10,
        pady=5
    )


    ttk.Label(
        frame,
        text=label,
        width=25
    ).pack(
        side="left"
    )


    entry = ttk.Entry(
        frame,
        textvariable=variable
    )

    entry.pack(
        side="left",
        fill="x",
        expand=True
    )


    ttk.Button(
        frame,
        text="Browse",
        command=lambda:
            browse_save(entry)
            if save
            else browse_file(entry)
    ).pack(
        side="left",
        padx=5
    )



# --------------------------------------------------
# Main window
# --------------------------------------------------

root = tk.Tk()

root.title(
    "DDON Translation JSON Builder"
)

root.geometry(
    "950x750"
)



tabs = ttk.Notebook(root)

tabs.pack(
    fill="both",
    expand=True
)



mapping_tab = ttk.Frame(tabs)

build_tab = ttk.Frame(tabs)



tabs.add(
    mapping_tab,
    text="Generate Mapping"
)


tabs.add(
    build_tab,
    text="Build JSON"
)



# --------------------------------------------------
# Mapping tab
# --------------------------------------------------

mapping_json = tk.StringVar()

mapping_csv = tk.StringVar()

mapping_output = tk.StringVar()



add_file_row(
    mapping_tab,
    "en-US JSON",
    mapping_json
)


add_file_row(
    mapping_tab,
    "English Master CSV",
    mapping_csv
)


add_file_row(
    mapping_tab,
    "Output Mapping",
    mapping_output,
    True
)



ttk.Button(
    mapping_tab,
    text="Generate Mapping",
    command=generate_mapping
).pack(
    pady=20
)



# --------------------------------------------------
# Build JSON tab
# --------------------------------------------------

build_mapping = tk.StringVar()

build_source_json = tk.StringVar()

build_language_csv = tk.StringVar()

build_output = tk.StringVar()



build_mode = tk.StringVar(
    value="Japanese"
)


translation_column = tk.StringVar(
    value="MsgEn"
)


build_locale = tk.StringVar(
    value="ja-JP"
)



add_file_row(
    build_tab,
    "Mapping JSON",
    build_mapping
)


add_file_row(
    build_tab,
    "Source JSON",
    build_source_json
)


add_file_row(
    build_tab,
    "Language CSV",
    build_language_csv
)


add_file_row(
    build_tab,
    "Output JSON",
    build_output,
    True
)



ttk.Label(
    build_tab,
    text="Build Mode"
).pack(
    pady=(15, 0)
)



mode_box = ttk.Combobox(
    build_tab,
    textvariable=build_mode,
    values=[
        "Japanese",
        "CSV Translation"
    ],
    state="readonly"
)

mode_box.pack()



ttk.Label(
    build_tab,
    text="Translation CSV Column"
).pack(
    pady=(15, 0)
)



ttk.Entry(
    build_tab,
    textvariable=translation_column
).pack()



ttk.Label(
    build_tab,
    text="Output Locale"
).pack(
    pady=(15, 0)
)



ttk.Entry(
    build_tab,
    textvariable=build_locale
).pack()



ttk.Button(
    build_tab,
    text="Build JSON",
    command=build_json
).pack(
    pady=20
)
# --------------------------------------------------
# Log window
# --------------------------------------------------

log_box = tk.Text(
    root,
    height=14
)

log_box.pack(
    fill="both",
    padx=10,
    pady=10
)



# --------------------------------------------------
# Start application
# --------------------------------------------------

root.mainloop()