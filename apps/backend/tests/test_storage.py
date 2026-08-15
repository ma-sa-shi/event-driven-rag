"""Presigned URLの発行先ホストはCloudFrontのCSP connect-srcと対になる契約であり、
boto3の既定値ではグローバルエンドポイントへ書き換わるため、ここで形を固定する。"""

from urllib.parse import parse_qs, urlparse

from app.storage import DocumentStorage
from tests.conftest import BUCKET_NAME

KEY = "documents/user-id/doc-id/architecture.md"


def test_presign_put_uses_regional_virtual_hosted_url():
    url = urlparse(DocumentStorage(BUCKET_NAME).presign_put(KEY))
    # CDKがCSPへ載せるbucketRegionalDomainNameと同じ形
    assert url.netloc == f"{BUCKET_NAME}.s3.ap-northeast-1.amazonaws.com"
    assert parse_qs(url.query)["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]


def test_presign_get_uses_regional_virtual_hosted_url():
    url = urlparse(DocumentStorage(BUCKET_NAME).presign_get(KEY))
    assert url.netloc == f"{BUCKET_NAME}.s3.ap-northeast-1.amazonaws.com"
    assert parse_qs(url.query)["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]


def test_presign_put_signs_the_content_type():
    url = urlparse(DocumentStorage(BUCKET_NAME).presign_put(KEY, "text/plain"))
    # SPAは発行時と同じContent-Typeをヘッダーで送る必要がある
    assert parse_qs(url.query)["X-Amz-SignedHeaders"] == ["content-type;host"]
