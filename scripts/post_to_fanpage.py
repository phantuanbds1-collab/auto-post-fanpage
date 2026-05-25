import os
import random
import requests
import anthropic
from pyairtable import Api
from datetime import datetime, timezone

AIRTABLE_TOKEN = os.environ["AIRTABLE_TOKEN"]
AIRTABLE_BASE_ID = "appRSWVVuHt2hKWlD"
AIRTABLE_TABLE_ID = "tblOxaBJbaP6YNlfD"
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
FB_PAGE_ACCESS_TOKEN = os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"]
FB_PAGE_ID = os.environ["FACEBOOK_PAGE_ID"]

FIELD_TIEU_DE = "Tiêu Đề"
FIELD_TEN_DUONG = "Tên Đường"
FIELD_SO_TANG = "Số Tầng"
FIELD_SO_PN = "Số Phòng Ngủ"
FIELD_DIEN_TICH = "Diện Tích Sử Dụng (m²)"
FIELD_GIA_BAN = "Giá Bán Mong Muốn"
FIELD_THONG_TIN = "Thông Tin Nhà"
FIELD_HUONG_NHA = "Hướng Nhà"
FIELD_HINH_ANH = "Hình Ảnh Nhà"
FIELD_TRANG_THAI = "Trạng Thái Giao Dịch"
FIELD_NGAY_DANG = "Ngày Đăng Cuối"


def get_listings():
    api = Api(AIRTABLE_TOKEN)
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID)
    records = table.all(
        formula=f"{{{FIELD_TRANG_THAI}}} = 'Chưa bán'",
        sort=[FIELD_NGAY_DANG],  # sort ascending → least recently posted first
    )
    return records


def pick_record(records):
    # Prefer records never posted, then least recently posted
    never_posted = [r for r in records if not r["fields"].get(FIELD_NGAY_DANG)]
    pool = never_posted if never_posted else records
    return random.choice(pool)


def generate_post_content(fields):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    info_lines = [
        f"- Tiêu đề: {fields.get(FIELD_TIEU_DE, '')}",
        f"- Địa chỉ: {fields.get(FIELD_TEN_DUONG, '')}",
        f"- Hướng nhà: {fields.get(FIELD_HUONG_NHA, '')}",
        f"- Số tầng: {fields.get(FIELD_SO_TANG, '')}",
        f"- Số phòng ngủ: {fields.get(FIELD_SO_PN, '')}",
        f"- Diện tích sử dụng: {fields.get(FIELD_DIEN_TICH, '')} m²",
        f"- Giá bán: {fields.get(FIELD_GIA_BAN, '')}",
        f"- Mô tả: {fields.get(FIELD_THONG_TIN, '')}",
    ]
    listing_info = "\n".join(line for line in info_lines if not line.endswith(": "))

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=(
            "Bạn là chuyên gia marketing bất động sản tại Việt Nam. "
            "Viết bài đăng Facebook thu hút, ngắn gọn, dùng emoji phù hợp, "
            "kết thúc bằng call-to-action kêu gọi liên hệ. Không nhắc đến số điện thoại."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Viết bài đăng Facebook (150–200 chữ, tiếng Việt) cho căn nhà phố sau:\n\n"
                    f"{listing_info}\n\n"
                    "Thêm hashtag cuối bài: #bất_động_sản #nhà_phố #cần_bán"
                ),
            }
        ],
    )
    return message.content[0].text


def upload_photo(image_url):
    resp = requests.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/photos",
        params={
            "access_token": FB_PAGE_ACCESS_TOKEN,
            "url": image_url,
            "published": "false",
        },
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json().get("id")
    print(f"  Ảnh upload thất bại: {resp.status_code} {resp.text}")
    return None


def post_to_facebook(content, image_urls):
    if image_urls:
        photo_ids = []
        for url in image_urls[:4]:  # Facebook tối đa 4 ảnh
            pid = upload_photo(url)
            if pid:
                photo_ids.append({"media_fbid": pid})

        if photo_ids:
            resp = requests.post(
                f"https://graph.facebook.com/{FB_PAGE_ID}/feed",
                params={"access_token": FB_PAGE_ACCESS_TOKEN},
                json={"message": content, "attached_media": photo_ids},
                timeout=30,
            )
            return resp

    return requests.post(
        f"https://graph.facebook.com/{FB_PAGE_ID}/feed",
        params={"access_token": FB_PAGE_ACCESS_TOKEN, "message": content},
        timeout=30,
    )


def update_last_posted(record_id):
    api = Api(AIRTABLE_TOKEN)
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    table.update(record_id, {FIELD_NGAY_DANG: now_iso})


def main():
    print("=== Auto Post Nhà Phố → Facebook Fan Page ===")

    print("Đang lấy danh sách nhà từ Airtable...")
    listings = get_listings()

    if not listings:
        print("Không có nhà nào với trạng thái 'Chưa bán'. Dừng lại.")
        return

    record = pick_record(listings)
    fields = record["fields"]
    print(f"Đã chọn: {fields.get(FIELD_TIEU_DE, record['id'])}")

    print("Đang tạo nội dung bài đăng với Claude AI...")
    content = generate_post_content(fields)
    print(f"\nNội dung:\n{'-'*40}\n{content}\n{'-'*40}\n")

    image_urls = [
        att["url"]
        for att in fields.get(FIELD_HINH_ANH, [])
        if isinstance(att, dict) and "url" in att
    ]
    print(f"Số ảnh đính kèm: {len(image_urls)}")

    print("Đang đăng lên Facebook Fan Page...")
    resp = post_to_facebook(content, image_urls)

    if resp.status_code == 200:
        post_id = resp.json().get("id", "N/A")
        print(f"Đăng thành công! Post ID: {post_id}")
        update_last_posted(record["id"])
        print("Đã cập nhật 'Ngày Đăng Cuối' trong Airtable.")
    else:
        print(f"Lỗi đăng bài: {resp.status_code} - {resp.text}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
