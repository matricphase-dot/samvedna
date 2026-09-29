# -*- coding: utf-8 -*-
"""Scripted demo call scenarios for the live prototype.

Each scenario is a list of windows streamed every few seconds:
{text, prosody{silence_ratio, avg_silence_s, pitch_var, rate_wps, tremor,
energy_var}}. Prosody values simulate what the real pipeline extracts with
librosa from the call audio (see README - prototype vs production map).
"""

CALM = dict(silence_ratio=0.12, avg_silence_s=0.6, pitch_var=0.30,
            rate_wps=2.9, tremor=0.10, energy_var=0.25)
MILD = dict(silence_ratio=0.28, avg_silence_s=1.4, pitch_var=0.45,
            rate_wps=2.3, tremor=0.30, energy_var=0.35)
TENSE = dict(silence_ratio=0.45, avg_silence_s=2.6, pitch_var=0.62,
             rate_wps=1.8, tremor=0.55, energy_var=0.45)
BREAKING = dict(silence_ratio=0.66, avg_silence_s=4.2, pitch_var=0.80,
                rate_wps=1.2, tremor=0.85, energy_var=0.55)

SCENARIOS = [
    {
        "id": "A",
        "label": "Caller A - Village boycott, escalating to CRITICAL (rail fires)",
        "language": "Hinglish",
        "repeat_calls": 0,
        "abandoned": False,
        "windows": [
            ("Namaste... meri baat suniye please. Gaon walon ne humara "
             "bahishkar kar diya hai.", MILD),
            ("Huqka pani band kar diya... koi baat nahi karta. Akela feel "
             "ho raha hai bahut.", {**TENSE, "tremor": 0.4}),
            ("Kal raat un logon ne meri pitaai ki... peeta mujhe. Zameen bhi "
             "cheen li, kabza kar liya.", {**TENSE, "tremor": 0.6}),
            ("Dhamka rahe hain ki gaon chhod do, warna dekh lenge... darr lag "
             "raha hai bahut. Raat ko neend nahi aati.", BREAKING),
            ("Koi madad nahi kar raha... sab khatam lagta hai. Umeed nahi "
             "bachi.", {**BREAKING, "silence_ratio": 0.72}),
            ("Mujhe lagta hai... jeena nahi hai ab. Sab khatam kar lunga. "
             "Koi nahi hai mera.", {**BREAKING, "tremor": 0.95, "rate_wps": 0.9}),
        ],
    },
    {
        "id": "B",
        "label": "Caller B - Threats + sleeplessness, lands HIGH",
        "language": "Hindi (romanized)",
        "repeat_calls": 1,
        "abandoned": False,
        "windows": [
            ("Hello, maine pichhli baar bhi call kiya tha. Log mujhe dhamka "
             "rahe hain, raat mein ghar ke bahar aate hain.", TENSE),
            ("Pati ko marne ke dhamki di hai unhone. Bahut darr lagta hai, "
             "bacchi akeli school nahi bhej sakti.", {**TENSE, "tremor": 0.65}),
            ("Udasi chhaya hai pura ghar. Khaana nahi khaya aaj. Koi saath "
             "nahi deta, sab dara hua hai.", {**BREAKING, "silence_ratio": 0.5}),
            ("Insaaf chahiye bas. Lekin ro rahi hoon main baar baar. Thak "
             "gayi hoon ladte ladte.", BREAKING),
        ],
    },
    {
        "id": "C",
        "label": "Caller C - Pension blocked + intimidation, lands MODERATE",
        "language": "Hinglish",
        "repeat_calls": 0,
        "abandoned": True,
        "windows": [
            ("Namaste, mera pension rok diya hai panchayat walo ne. Paisa "
             "nahi mil raha teen mahine se.", MILD),
            ("Office gaya toh dara diya... daraya mujhe. Thoda darr bhi lagta "
             "hai par darr nahi lag raha ab utna.", MILD),
            ("Kya karoon samajh nahi aa raha. Madad chahiye bas, insaaf "
             "chahiye.", {**MILD, "tremor": 0.35}),
        ],
    },
    {
        "id": "D",
        "label": "Caller D - Process inquiry, stays LOW (healthy baseline)",
        "language": "English",
        "repeat_calls": 0,
        "abandoned": False,
        "windows": [
            ("Hi, I wanted to understand the process for registering a "
             "complaint on the portal.", CALM),
            ("Okay, and what documents would I need to carry to the district "
             "office?", CALM),
            ("Got it, thank you so much for the help.", CALM),
        ],
    },
]

# Repeat-caller trajectory demo: 2 prior sessions already in DB, 3rd is live
REPEAT_HISTORY = [
    {"svi": 41, "tier": "MODERATE", "note": "Call 1 (4 days ago): boycott "
     "reported, caller hesitated, closed as inquiry."},
    {"svi": 58, "tier": "HIGH", "note": "Call 2 (2 days ago): threats "
     "mentioned, distress rising, no follow-up happened."},
]

TIER_ACTIONS = {
    "LOW": ["Share information pamphlet", "Log for records"],
    "MODERATE": ["Connect to helpline counsellor", "Schedule follow-up call"],
    "HIGH": ["Priority counsellor connect", "Legal-aid referral",
             "Medical helpline referral", "Flag to district officer"],
    "CRITICAL": ["IMMEDIATE counsellor takeover", "Emergency support protocol",
                 "Police liaison (if threat to life)", "Witness-protection "
                 "assessment", "Supervisor notification"],
}
