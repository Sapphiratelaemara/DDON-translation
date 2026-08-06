import json
import shutil
from pathlib import Path

cfg_path = Path(r"c:\DDON-translation\Dialogue Editor\config\en\formatter_config.json")
backup_path = cfg_path.with_suffix('.json.bak')

with cfg_path.open('r', encoding='utf-8-sig') as f:
    data = json.load(f)

# Backup
shutil.copy2(cfg_path, backup_path)

# Remove legacy keys if present
for key in ('ai_system_prompt', 'pretranslate_system_prompt'):
    if key in data:
        del data[key]

# Punctuation paragraph from main.py
punct_par = (
    "Punctuation discipline: The ellipses in the above examples illustrate syntactic hesitation (clause breaks, "
    "self-corrections, qualifying phrases). They do NOT license replacing source punctuation. Preserve every `!` `?` "
    "as mapped in the translation guidance. Hesitation is conveyed by sentence structure and word choice, not by "
    "inserting `...` where the source has none.\n\n"
)

# Ensure ai_prompt exists
ai = data.get('ai_prompt', '')
if 'Punctuation discipline:' not in ai:
    # Attempt to insert after the {character_voice_note} placeholder if present
    marker = '{character_voice_note}\n\n'
    if marker in ai:
        ai = ai.replace(marker, marker + punct_par)
    else:
        # Prepend the paragraph near the top after OUTPUT FORMAT section if possible
        of_marker = 'OUTPUT FORMAT:\nReturn only the translated or refined text. No preamble, no explanation, no quotation marks.'
        if of_marker in ai:
            ai = ai.replace(of_marker, of_marker + '\n\n' + punct_par)
        else:
            # Fallback: append to end
            ai = ai + '\n\n' + punct_par
    data['ai_prompt'] = ai

# Write back with nice formatting
with cfg_path.open('w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('Updated', cfg_path)
print('Backup saved to', backup_path)
