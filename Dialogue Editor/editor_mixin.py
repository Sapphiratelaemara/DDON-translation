"""
editor_mixin.py — SharedEditorMixin

Methods shared verbatim (or near-verbatim) between ReviewEditor and
CSVTranslationWindow.  Neither class is a sub-class of the other; the mixin
provides the shared behaviour through multiple inheritance:

    class ReviewEditor(SharedEditorMixin, tk.Toplevel): ...
    class CSVTranslationWindow(SharedEditorMixin, tk.Toplevel): ...

CONTRACT — the following attributes MUST exist on `self` before any mixin
method is called.  They are set by the concrete class's __init__ / _setup_ui:

    Widget references
        self.txt                — main English Text editor
        self.deepl_box          — DeepL suggestion Text widget
        self.chat_history       — AI chat history Text widget
        self.chat_input         — AI chat input Text widget
        self.chat_model_var     — StringVar for selected model
        self.chat_model_combo   — Combobox for model selection
        self.btn_chat_send      — Button (disabled while chatting)
        self.preview_canvas     — Canvas for in-game preview
        self._preview_box_var   — StringVar ("dialogue" | "choice")

    State
        self.cm                 — ConfigManager instance
                                  (ReviewEditor exposes this via a @property)
        self.lore_engine        — LoreEngine instance
        self.anach_ranges       — list[(start, end, word, suggestions)]
        self._box_meta          — dict of box layout metadata
        self._preview_base_images — dict[str, PIL.Image]
        self._preview_font_objs   — dict[str, PIL.ImageFont]
        self._tip_label         — tk.Label tooltip widget
        self._tip_visible       — bool
        self._hovered_range     — current hovered range tuple or None
        self._is_translating    — bool busy-flag
        self._is_chatting       — bool busy-flag
        self._prev_W, _prev_H   — fallback canvas dimensions
        self.colors             — dict of themed colour strings

    Methods provided by the concrete class
        self._update_counters() — refresh line-length counter strip
"""

import re
import threading
import tkinter as tk
from tkinter import messagebox

try:
    from PIL import ImageDraw, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class SharedEditorMixin:

    # ------------------------------------------------------------------
    # Anachronism tooltip
    # ------------------------------------------------------------------

    def _build_suggestion_text(self, word):
        """Return tooltip text: archaic alternatives + cached definition.
        Checks 'modern→archaic' context override first, then generic."""
        from lore_engine import IN_UNIVERSE_VOCAB
        word_lower = word.lower()
        options = []
        if word_lower in IN_UNIVERSE_VOCAB:
            val = IN_UNIVERSE_VOCAB[word_lower]
            if val:
                options.append(val)
        if not options:
            return f'⚠ "{word}" — no direct replacement (flag only)'
        opts_str = "  /  ".join(options)
        tip = f'⚠ "{word}"  →  {opts_str}   (Tab to insert)'
        for archaic in options:
            override_key = f"{word_lower}→{archaic.lower()}"
            defn = self.lore_engine.get_definition(override_key)
            if not defn:
                defn = self.lore_engine.get_definition(archaic.lower())
            if defn:
                tip += f"\n{defn}"
                break
        return tip

    def _bind_tooltip(self):
        """Bind hover tooltip to self.txt. Safe to call multiple times."""
        if hasattr(self, "_tip_label") and self._tip_label.winfo_exists():
            self._tip_label.destroy()
        self._tip_label = tk.Label(
            self, text="", bg="#ffffe0", fg="black",
            relief="solid", borderwidth=1, font=("Arial", 9),
            wraplength=400, justify="left",
        )
        self._tip_visible = False
        self._hovered_range = None

        def on_motion(event):
            idx = self.txt.index(f"@{event.x},{event.y}")
            for entry in self.anach_ranges:
                start, end, word, _ = entry
                if self.txt.compare(start, "<=", idx) and self.txt.compare(idx, "<", end):
                    self._tip_label.config(text=self._build_suggestion_text(word))
                    self._tip_label.place(
                        x=event.x_root - self.winfo_rootx() + 20,
                        y=event.y_root - self.winfo_rooty() + 10,
                    )
                    self._tip_label.lift()
                    self._tip_visible = True
                    self._hovered_range = entry
                    return
            if self._tip_visible:
                self._tip_label.place_forget()
                self._tip_visible = False
            self._hovered_range = None

        def on_leave(event):
            if self._tip_visible:
                self._tip_label.place_forget()
                self._tip_visible = False
            self._hovered_range = None

        self.txt.bind("<Motion>", on_motion)
        self.txt.bind("<Leave>",  on_leave)

    def _tab_insert_suggestion(self, event):
        """On Tab: replace the hovered or cursor-position word with its
        archaic suggestion. Hover takes priority so mouse workflow is natural."""
        if self._hovered_range:
            start, end, word, suggestions = self._hovered_range
        else:
            idx = self.txt.index(tk.INSERT)
            match = next(
                ((s, e, w, sg) for s, e, w, sg in self.anach_ranges
                 if self.txt.compare(s, "<=", idx) and self.txt.compare(idx, "<=", e)),
                None,
            )
            if not match:
                return None   # not on a highlight — allow normal Tab
            start, end, word, suggestions = match

        if not suggestions:
            return "break"

        replacement      = suggestions[0][0]
        matched          = self.txt.get(start, end)
        first_alpha_orig = next((c for c in matched      if c.isalpha()), None)
        first_alpha_idx  = next((i for i, c in enumerate(replacement) if c.isalpha()), None)
        if first_alpha_orig and first_alpha_orig.isupper() and first_alpha_idx is not None:
            replacement = (
                replacement[:first_alpha_idx]
                + replacement[first_alpha_idx].upper()
                + replacement[first_alpha_idx + 1:]
            )
        self.txt.delete(start, end)
        self.txt.insert(start, replacement)
        self.txt.tag_remove("anachronism", start, f"{start}+{len(replacement)}c")
        if self._tip_visible:
            self._tip_label.place_forget()
            self._tip_visible = False
        self._hovered_range = None
        self._update_counters()
        return "break"

    # ------------------------------------------------------------------
    # In-game preview
    # ------------------------------------------------------------------

    def _update_preview(self, e=None):
        box_key  = self._preview_box_var.get()
        meta     = self._box_meta.get(box_key)
        base_img = self._preview_base_images.get(box_key)
        fnt      = self._preview_font_objs.get(box_key)
        if not fnt or not _PIL_OK or not base_img:
            return
        vis_text = re.sub(r"<[^>]+>", "", self.txt.get(1.0, tk.END).strip("\n"))
        lines    = vis_text.splitlines()
        img_w    = meta.get("img_w", self._prev_W)
        img_h    = meta.get("img_h", self._prev_H)
        self.preview_canvas.config(width=img_w, height=img_h)
        render   = base_img.copy()
        draw     = ImageDraw.Draw(render)
        pad, fg  = meta["pad"], meta["fg"]
        tw       = img_w - 2 * pad
        COMPRESS = 0.90
        wrapped  = []
        for line in lines:
            buf = ""
            for word in line.split():
                test = buf + (" " if buf else "") + word
                if fnt.getlength(test) * COMPRESS > tw:
                    wrapped.append(buf)
                    buf = word
                else:
                    buf = test
            if buf:
                wrapped.append(buf)
        line_h = meta["line_h"]
        for i, line in enumerate(wrapped[:6]):
            draw.text((pad + 15, pad + i * line_h), line, font=fnt, fill=fg)
        if len(wrapped) > 6:
            draw.text(
                (pad + 15, pad + 6 * line_h - 12),
                f"▼ +{len(wrapped) - 6} lines clipped",
                fill="#ff4444",
            )
        self._current_preview_tk = ImageTk.PhotoImage(render)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self._current_preview_tk)

    # ------------------------------------------------------------------
    # DeepL
    # ------------------------------------------------------------------

    def translate_with_deepl(self):
        source_text = self.jp_txt.get(1.0, tk.END).strip()
        if not source_text or self._is_translating:
            return

        cached = self.cm.get_cached("deepl", source_text)
        if cached:
            self.deepl_box.config(state="normal")
            self.deepl_box.delete(1.0, tk.END)
            self.deepl_box.insert(tk.END, cached)
            self.deepl_box.config(state="disabled")
            return

        key = self.cm.get_key("deepl_api_key")
        if not key:
            return   # silently skip — user can set key in Options

        self._is_translating = True
        self.deepl_box.config(state="normal")
        self.deepl_box.delete(1.0, tk.END)
        self.deepl_box.insert(tk.END, "Translating...")
        self.deepl_box.config(state="disabled")

        def worker():
            from api_handler import DeepLClient
            client      = DeepLClient(key)
            target_lang = self.cm.config.get("deepl_target_lang", "EN-US")
            res         = client.translate(source_text, target_lang=target_lang)

            def finalize():
                self.deepl_box.config(state="normal")
                self.deepl_box.delete(1.0, tk.END)
                if "text" in res:
                    self.deepl_box.insert(tk.END, res["text"])
                    self.cm.set_cached("deepl", source_text, res["text"])
                else:
                    self.deepl_box.insert(tk.END, f"ERROR: {res.get('error')}")
                self.deepl_box.config(state="disabled")
                self._is_translating = False

            self.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def click_deepl_suggestion(self, event=None):
        """Paste the DeepL suggestion into the main editor."""
        suggestion = self.deepl_box.get(1.0, tk.END).strip()
        if suggestion and suggestion != "Translating..." and not suggestion.startswith("ERROR"):
            current = self.txt.get(1.0, tk.END).strip()
            if current and not messagebox.askyesno(
                "Overwrite", "Overwrite current English text with DeepL suggestion?", parent=self
            ):
                return
            self.txt.delete(1.0, tk.END)
            self.txt.insert(tk.END, suggestion)
            self._update_counters()
            self._update_preview()

    # ------------------------------------------------------------------
    # AI chat
    # ------------------------------------------------------------------

    def _save_selected_model(self, e=None):
        model = self.chat_model_var.get()
        self.cm.config["selected_openrouter_model"] = model
        self.cm.save_all()

    def clear_chat(self):
        self.chat_history.config(state="normal")
        self.chat_history.delete(1.0, tk.END)
        self.chat_history.config(state="disabled")

    def add_chat_context(self):
        jp = self.jp_txt.get(1.0, tk.END).strip()
        en = self.txt.get(1.0, tk.END).strip()
        self.chat_input.insert(tk.END, f"\n[Context]\nJP: {jp}\nEN: {en}\n")
        self.chat_input.see(tk.END)

    def _chat_on_return(self, e):
        if not e.state & 0x1:   # Shift not held
            self.send_ai_chat()
            return "break"

    def refresh_model_list(self):
        """Reload the model list from config (updated in Options)."""
        models  = self.cm.config.get("openrouter_models", ["openrouter/auto"])
        self.chat_model_combo.config(values=models)
        current = self.chat_model_var.get()
        if current not in models:
            self.chat_model_var.set("openrouter/auto")
        messagebox.showinfo("AI Assistant", "Model list reloaded from configuration.")

    def send_ai_chat(self):
        if self._is_chatting:
            return
        key = self.cm.get_key("openrouter_api_key")
        if not key:
            messagebox.showwarning("OpenRouter", "No OpenRouter API key found in Options.")
            return

        user_msg = self.chat_input.get(1.0, tk.END).strip()
        if not user_msg:
            return

        model     = self.chat_model_var.get()
        cache_key = f"{model}::{user_msg}"
        cached    = self.cm.get_cached("openrouter", cache_key)
        if cached:
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
            self.chat_history.tag_config("user", foreground=self.colors["counter_fg"],
                                         font=("Arial", 9, "bold"))
            self.chat_history.insert(tk.END, f"\nAI: {cached}\n", "ai")
            self.chat_history.tag_config("ai", foreground=self.colors["fg"])
            self.chat_history.see(tk.END)
            self.chat_history.config(state="disabled")
            self.chat_input.delete(1.0, tk.END)
            return

        self._is_chatting = True
        self.btn_chat_send.config(state="disabled", text="...")
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"\nYOU: {user_msg}\n", "user")
        self.chat_history.tag_config("user", foreground=self.colors["counter_fg"],
                                     font=("Arial", 9, "bold"))
        self.chat_history.see(tk.END)
        self.chat_history.config(state="disabled")
        self.chat_input.delete(1.0, tk.END)

        def worker():
            from api_handler import OpenRouterClient
            client   = OpenRouterClient(key)
            messages = [
                {"role": "system", "content": (
                    "You are a DDON localization assistant. Help the user translate or "
                    "refine dialogue while respecting the game's medieval fantasy tone "
                    "and character archetypes."
                )},
                {"role": "user", "content": user_msg},
            ]
            res = client.chat(messages, model=model)

            def finalize():
                self.chat_history.config(state="normal")
                if "text" in res:
                    self.chat_history.insert(tk.END, f"\nAI: {res['text']}\n", "ai")
                    self.chat_history.tag_config("ai", foreground=self.colors["fg"])
                    self.cm.set_cached("openrouter", cache_key, res["text"])
                else:
                    self.chat_history.insert(tk.END, f"\nERROR: {res.get('error')}\n", "error")
                    self.chat_history.tag_config("error", foreground="#ff4444")
                self.chat_history.see(tk.END)
                self.chat_history.config(state="disabled")
                self._is_chatting = False
                self.btn_chat_send.config(state="normal", text="Send")

            self.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()
