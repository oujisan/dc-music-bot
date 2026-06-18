import yt_dlp
import json

ydl_opts = {
    'quiet': True,
    'extract_flat': False
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
    
    subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})
    
    print("Manual Subs:", list(subs.keys()))
    print("Auto Subs:", list(auto_subs.keys())[:5])
    
    if "en" in subs:
        print("\nEnglish Manual Sub Formats:")
        for fmt in subs["en"]:
            print(f"- {fmt.get('ext')}: {fmt.get('url')[:50]}...")
            
    elif "en" in auto_subs:
        print("\nEnglish Auto Sub Formats:")
        for fmt in auto_subs["en"]:
            print(f"- {fmt.get('ext')}: {fmt.get('url')[:50]}...")
