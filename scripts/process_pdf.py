#!/usr/bin/env python3
"""
taisyaku.jp PDF監視・処理スクリプト
"""
import os, io, re, json, ftplib, smtplib, httpx
import japanese_holiday as jpholiday
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
from PIL import Image
import pdfplumber
from pdf2image import convert_from_bytes
import anthropic

JST      = timezone(timedelta(hours=9))
NOW      = datetime.now(JST)
BASE_URL = "https://www.taisyaku.jp"
SEEN_PATH = Path("data/seen_urls.json")

# PDFファイル名パターン
PDF_SUFFIXES = [
    ("seigen",         "制限措置"),
    ("seigenkaizyo",   "制限措置解除"),
    ("gobatei",        "品貸料10倍"),
    ("gobateikaizyo",  "品貸料10倍解除"),
    ("tokubetsu",      "特別措置"),
]

# ─── 時間・祝日チェック ──────────────────────────────
def is_business_hours() -> bool:
    if NOW.weekday() >= 5:           # 土日
        return False
    if jpholiday.is_holiday(NOW):    # 祝日
        return False
    if NOW.hour < 8 or NOW.hour >= 21:
        return False
    return True

# ─── 処理済みURL管理 ────────────────────────────────
def load_seen() -> list:
    SEEN_PATH.parent.mkdir(exist_ok=True)
    return json.loads(SEEN_PATH.read_text("utf-8")) if SEEN_PATH.exists() else []

def save_seen(seen: list):
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2), "utf-8")

# ─── PDF URL探索 ────────────────────────────────────
def find_new_pdf_urls(seen: list) -> list:
    """今日の日付でPDF URLを生成して存在確認"""
    date_str = NOW.strftime("%Y%m%d")
    new_urls = []

    for suffix, _ in PDF_SUFFIXES:
        # 複数件対応: _seigen.pdf / _seigen2.pdf / _seigen3.pdf ...
        for n in [""] + [str(i) for i in range(2, 6)]:
            url = f"{BASE_URL}/media/{date_str}_{suffix}{n}.pdf"
            if url in seen:
                continue
            try:
                r = httpx.head(url, timeout=10, follow_redirects=True)
                if r.status_code == 200:
                    new_urls.append(url)
                    print(f"[NEW] {url}")
            except Exception:
                pass

    return new_urls

# ─── PDFテキスト抽出 ────────────────────────────────
def extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)

# ─── PDFキャプチャ生成 ──────────────────────────────
def pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
    """全ページをPNG画像に変換（200dpi・鮮明）"""
    pages = convert_from_bytes(pdf_bytes, dpi=200)
    images = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG", optimize=True)
        images.append(buf.getvalue())
    return images

# ─── PDFパース ──────────────────────────────────────
def parse_pdf(text: str, url: str) -> dict:
    """URLのsuffixで種別判定してパース"""
    if "_gobatei" in url and "kaizyo" not in url:
        return parse_gobatei(text)
    else:
        return parse_seigen(text)

def parse_seigen(text: str) -> dict:
    result = {
        "type": "seigen",
        "shahatsu": "",
        "date": "",
        "chui_list": [],
        "teishi_list": [],
        "teishi_date": "",
    }

    m = re.search(r"社発第\s*(T-\d+)\s*号", text)
    if m:
        result["shahatsu"] = m.group(1)

    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        result["date"] = f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    m = re.search(r"実施日[^:：]*[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        result["teishi_date"] = f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    # 注意喚起セクション
    chui_sec = _section(text, "注意喚起", ["申込停止", "２．", "2．", "以 上"])
    result["chui_list"] = _stocks(chui_sec)

    # 申込停止セクション
    teishi_sec = _section(text, "申込停止", ["以 上", "以上", "（停止の対象）"])
    result["teishi_list"] = _stocks(teishi_sec)

    return result

def parse_gobatei(text: str) -> dict:
    result = {
        "type": "gobatei",
        "shahatsu": "",
        "date": "",
        "stocks": [],
        "jisshi_date": "",
    }

    m = re.search(r"社発第\s*(T-\d+)\s*号", text)
    if m:
        result["shahatsu"] = m.group(1)

    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        result["date"] = f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    m = re.search(r"実施日[^:：]*[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        result["jisshi_date"] = f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日"

    result["stocks"] = _stocks(text)
    return result

def _section(text, start_kw, end_kws):
    s = text.find(start_kw)
    if s == -1:
        return ""
    e = len(text)
    for kw in end_kws:
        pos = text.find(kw, s + len(start_kw))
        if 0 < pos < e:
            e = pos
    return text[s:e]

def _stocks(text) -> list[dict]:
    stocks = []
    seen_codes = set()
    for m in re.finditer(r"(\d{4,5})\s+([\u3040-\u9fff\uff00-\uffefa-zA-Z（）㈱&\s・]+)", text):
        code = m.group(1)
        name = re.sub(r"\s+", "", m.group(2)).strip("・（）")
        if code not in seen_codes and name and len(name) >= 2:
            stocks.append({"code": code, "name": name})
            seen_codes.add(code)
    return stocks

# ─── ツイート下書き生成 ──────────────────────────────
def make_tweet(parsed: dict) -> str:
    if parsed["type"] == "gobatei":
        return make_tweet_gobatei(parsed)
    else:
        return make_tweet_seigen(parsed)

def make_tweet_seigen(d: dict) -> str:
    lines = [
        "#日証金",
        "#貸借取引の銘柄別制限措置の実施等について",
        f"社発第{d['shahatsu']}号",
        d["date"],
    ]
    if d["chui_list"]:
        lines.append("")
        lines.append("⚠️注意喚起")
        for s in d["chui_list"]:
            lines.append(f"（{s['code']}）{s['name']}")
    if d["teishi_list"]:
        lines.append("")
        lines.append("🚫申込停止措置")
        if d["teishi_date"]:
            lines.append(f"実施日（約定日）:{d['teishi_date']}")
        for s in d["teishi_list"]:
            lines.append(f"（{s['code']}）{s['name']}")
    lines += [
        "",
        "🔸停止対象",
        "・制度信用新規売りに伴う貸株申込および融資返済申込",
        "・制度信用買いの現引きに伴う融資返済申込および貸株申込",
        "※弁済繰延期限到来分は一部対象外",
        "※東証銘柄はPTS対象銘柄にも同様措置適用",
        "※正確な内容は適時開示参照の事",
    ]
    return "\n".join(lines)

def make_tweet_gobatei(d: dict) -> str:
    lines = [
        "#日証金",
        "#貸借取引品貸し申込みにおける品貸料の最高料率10倍適用について",
        f"社発第{d['shahatsu']}号",
        d["date"],
        "",
        "🚫最高料率10倍適用",
    ]
    if d["jisshi_date"]:
        lines.append(f"実施日（約定日）:{d['jisshi_date']}")
    for s in d["stocks"]:
        lines.append(f"（{s['code']}）{s['name']}")
    lines += [
        "",
        "🔸内容",
        "・貸借取引品貸し申込みにおける品貸料の最高料率を10倍とする臨時措置",
        "※正確な内容は適時開示参照の事",
    ]
    return "\n".join(lines)

# ─── メール送信 ──────────────────────────────────────
def send_email(tweet: str, images: list[bytes], pdf_url: str):
    msg = MIMEMultipart()
    msg["From"]    = os.environ["GMAIL_USER"]
    msg["To"]      = os.environ["NOTIFY_EMAIL"]
    msg["Subject"] = f"⚠️【日証金】新着通知 {NOW.strftime('%Y/%m/%d %H:%M')}"

    body = f"【ツイート下書き】\n{'='*40}\n{tweet}\n{'='*40}\n\nPDF: {pdf_url}"
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for i, img_bytes in enumerate(images):
        img = MIMEImage(img_bytes, _subtype="png")
        img.add_header("Content-Disposition", "attachment", filename=f"page_{i+1}.png")
        msg.attach(img)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASS"])
        smtp.send_message(msg)
    print("[MAIL] 送信完了")

# ─── FTP・ウェブデータ更新 ───────────────────────────
def update_web_data(parsed: dict, pdf_url: str):
    """申込停止銘柄をdata.jsonに追記してFTPアップロード"""
    # ローカルのdata.jsonを読み込み
    data_path = Path("web/data.json")
    data_path.parent.mkdir(exist_ok=True)
    records = json.loads(data_path.read_text("utf-8")) if data_path.exists() else []

    # 申込停止銘柄だけ記録
    teishi_list = parsed.get("teishi_list", parsed.get("stocks", []))
    teishi_date = parsed.get("teishi_date", parsed.get("jisshi_date", ""))

    for stock in teishi_list:
        # 重複チェック（同日同コード）
        exists = any(
            r["code"] == stock["code"] and r["teishi_date"] == teishi_date
            for r in records
        )
        if not exists:
            records.append({
                "code":        stock["code"],
                "name":        stock["name"],
                "teishi_date": teishi_date,
                "pdf_url":     pdf_url,
                "shahatsu":    parsed.get("shahatsu", ""),
                "type":        parsed["type"],
            })

    # 日付降順でソート
    records.sort(key=lambda x: x["teishi_date"], reverse=True)
    data_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), "utf-8")

    # FTPアップロード
    ftp_upload(data_path, "data.json")
    print("[FTP] data.json アップロード完了")

def ftp_upload(local_path: Path, remote_filename: str):
    remote_path = os.environ.get("FTP_REMOTE_PATH", "/public_html/taisyaku/")
    with ftplib.FTP() as ftp:
        ftp.connect(os.environ["FTP_HOST"])
        ftp.login(os.environ["FTP_USER"], os.environ["FTP_PASS"])
        ftp.cwd(remote_path)
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_filename}", f)

# ─── メイン ─────────────────────────────────────────
def main():
    if not is_business_hours():
        print(f"[SKIP] 営業時間外 ({NOW.strftime('%Y-%m-%d %H:%M')} JST)")
        return

    seen     = load_seen()
    new_urls = find_new_pdf_urls(seen)

    if not new_urls:
        print("[INFO] 新着なし")
        return

    for url in new_urls:
        print(f"\n[PROCESS] {url}")
        try:
            pdf_bytes = httpx.get(url, timeout=30, follow_redirects=True).content
            text      = extract_text(pdf_bytes)
            images    = pdf_to_images(pdf_bytes)
            parsed    = parse_pdf(text, url)
            tweet     = make_tweet(parsed)

            print(f"[TWEET]\n{tweet}\n")

            send_email(tweet, images, url)
            update_web_data(parsed, url)

            seen.append(url)
        except Exception as e:
            print(f"[ERR] {url}: {e}")

    save_seen(seen)

if __name__ == "__main__":
    main()
