# 🛠 Setup Guide — for your own computer (Windows / Mac / Linux)

You have 2FA on your account — perfect, stay secure. This guide assumes **zero
coding experience**. Follow the steps in order. ~15 minutes total.

---

## Step 1 — Get the project folder

Download `telegram-digest.zip` from this workspace and **extract it** anywhere
convenient (e.g. your Desktop). You'll get a folder called `telegram-digest`.

Your Telegram app credentials (`api_id`, `api_hash`) are **already filled in**
inside the `.env` file — one less thing to do. The only thing left to add is
your phone number (Step 3).

## Step 2 — Install Python

- **Windows:** go to <https://www.python.org/downloads/> → click the big yellow
  **Download Python** button → run the installer → ⚠️ **tick the box
  "Add python.exe to PATH" on the first screen** → Install.
- **Mac:** Python is usually pre-installed — check by opening *Terminal* and
  typing `python3 --version`. If it's missing, install from the same link.

Verify it worked — open a terminal:

- **Windows:** press `Win + R`, type `cmd`, press Enter.
- **Mac:** open *Terminal* from Applications → Utilities.

Type this and press Enter — you should see `Python 3.xx.xx`:

```bash
python --version
```
*(On Mac, use `python3` instead of `python` in every command below.)*

## Step 3 — Add your phone number

1. Open the `telegram-digest` folder, open the file named **`.env`** with
   Notepad (Windows) or TextEdit (Mac).
2. Find the line `TG_PHONE=` and add your number in international format:
   `TG_PHONE=+2519XXXXXXXX`
3. Save and close.

> 💡 Can't see `.env` on Windows? In File Explorer: View → tick
> **File name extensions** and **Hidden items**. Or just skip this step —
> the login will simply ask for your phone number when you run it.

## Step 4 — Install the bot's dependencies

In the terminal, go into the folder (adjust the path to where you extracted it):

```bash
cd Desktop\telegram-digest        # Windows
cd ~/Desktop/telegram-digest      # Mac/Linux
```

Then run:

```bash
pip install -r requirements.txt
```

*(On Mac: `pip3 install -r requirements.txt`.)*
Wait until it finishes (~30 seconds). Red text about versions is usually harmless.

## Step 5 — One-time login 🔑 (the only interactive step)

```bash
python main.py auth
```

You'll be asked for things **one at a time**:

1. **The code Telegram just sent you** — check your Telegram app; you'll get an
   official message from "Telegram" with a login code. Type it and press Enter.
2. **Your 2FA password** — the one you created in Telegram's Two-Step
   Verification. You won't see characters as you type (that's normal). Enter.

✅ Success looks like: `Logged in as <your name>` + `Session saved`.

> 🔒 Your code and password are used **only** by the login on your own machine.
> A `session/` folder is created — it keeps you logged in, so you never have to
> do this step again (unless you delete it).

## Step 6 — Your first real digest 🎉

```bash
python main.py run
```

Watch the log — it will list every channel being scanned. When it's done, open
Telegram: a new **private channel called "My Daily Digest"** (auto-created for
you) now contains your first digest, grouped by topic with links to originals.

## Step 7 — Run it daily

```bash
python main.py serve
```

Leave this window open (minimize it). It will now deliver the digest **every
day at 08:00**. If you restart your computer, just run the same command again.

💡 Anytime you want a digest immediately: send **`!digest now`** to your own
**Saved Messages** in Telegram.

---

## 🩹 If something goes wrong

| What you see | What to do |
|---|---|
| `'python' is not recognized` | Python wasn't added to PATH. Reinstall and **tick "Add python.exe to PATH"**. |
| `pip: command not found` | Use `pip3` / `python3` (Mac), or reinstall Python (Windows). |
| Phone number or code "invalid" | Code expires fast — rerun `python main.py auth` and enter the **new** code quickly. |
| `SESSION_PASSWORD_NEEDED` | That's just it asking for your 2FA password — type it (invisible typing is normal). |
| `AuthKeyDuplicatedError` | Two copies running. Close one, or delete the `session` folder and redo Step 5. |

## ▶️ Optional: free AI semantic matching on your machine

Keywords already work great. To also catch paraphrased posts (e.g. "100%
scholarship tutorial" matching a "free courses" topic) with **no API costs**:

```bash
pip install sentence-transformers
```
…then in `.env` change `AI_PROVIDER=off` to `AI_PROVIDER=local`. It downloads a
small model once (~100 MB) and then runs fully offline.
