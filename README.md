# 🩺 PromptCare- Medical Reminder Agent

## 🤖 Project Overview

The **Medical Reminder Agent** is an intelligent, conversational AI assistant designed to help patients manage their health-related tasks — such as taking medication, checking vitals, or exercising — through timely reminders and empathetic follow-ups. 

Built with **LangChain**, **Ollama** (or other local LLMs), **Telegram Bot API**, **SQLite**, and **APScheduler**, this agent interacts naturally with users, parses flexible human input, and schedules reminders with escalating urgency. It also logs interactions and understands task priorities based on user-defined urgency levels (Relaxed, General, Urgent).

✨ Key Features

- **Conversational AI:** Understands natural language inputs and chats like a virtual healthcare assistant.
- **Flexible Input Parsing:** Accepts free-form phrases like "Remind me to check my BP in 1 hour".
- **Urgency Levels:** User-selectable urgency (Relaxed – 15 min, General – 5 min, Urgent – 2 min).
- **Reminder Follow-ups:** Sends gentle, moderate, or aggressive follow-ups based on urgency if a task is missed.
- **Interactive Telegram Bot:** Fully integrated with Telegram for 24/7 patient interaction.
- **Lightweight and Local:** Runs offline with support for open-source LLMs (e.g., Mistral via Ollama).
- **Extensible Logging:** Logs completed and missed tasks for future use (e.g., analytics, audits).
- **Modular Codebase:** Designed for easy enhancement (e.g., task cancellation, multi-patient support).

🛠️ Technologies Used

- Python 3.12+
- LangChain
- Ollama / Mistral (or compatible LLMs)
- Telegram Bot API
- APScheduler
- SQLite
- pytz, tzlocal, dateutil

⚖️ Copyright Notice

This project, including its source code, design, and structure, is Copyright © 2025 Hari Adapala. All rights reserved.

It is protected under:

U.S. Copyright Act of 1976 (17 U.S. Code § 101 et seq.)

Digital Millennium Copyright Act (DMCA)

Berne Convention for the Protection of Literary and Artistic Works, to which over 180 countries are signatories

You may not copy, reproduce, modify, distribute, publish, transmit, or create derivative works from this project without express written permission from the author, unless explicitly allowed by the license terms below.

❌ Strictly Prohibited (Without Written Permission)
❌ Claiming authorship of this project or any of its parts

❌ Submitting it as coursework, portfolio, or personal project

❌ Rebranding and sharing it on GitHub, Replit, HuggingFace, or any other platform

❌ Commercial use or monetization in any form

❌ Training models or datasets on this code without permission

✅ Permitted (With Attribution)
✅ Studying the code for personal learning and inspiration

✅ Forking the repository with visible credit to the original author (Hari Adapala)

✅ Contributing to the project via pull requests or issues, under the same license

📜 License

This project is licensed under a custom "No Derivatives / No Commercial Use" License, based on CC BY-NC-ND 4.0:

You may share this work with attribution for non-commercial purposes only. You may not adapt, remix, transform, or build upon this code without explicit permission.


🛡️ Enforcement and Penalties

If this code is found plagiarized or redistributed without permission:

A DMCA takedown notice will be filed against the infringing repository or platform

Evidence will be submitted to academic integrity offices, hiring managers, or competition boards

Legal action may be pursued under U.S. or international copyright law

This repository contains invisible watermarking and version tracking for verification.


📬 To request permission, report misuse, or contribute officially, contact:
Hari Adapala – hadapala333@gmail.com
