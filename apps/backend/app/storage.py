import boto3
from botocore.config import Config

# presigned URLはLambdaロールで署名されるため、実行ロールに対象操作の権限が必要
# 長すぎるとURL漏洩時のリスクが増すため15分に制限
UPLOAD_URL_EXPIRES_IN = 900
DOWNLOAD_URL_EXPIRES_IN = 900

# 既定のboto3はリージョンを落としたグローバルエンドポイント(<bucket>.s3.amazonaws.com)へ
# 書き換え、非推奨のSigV2で署名する。SPAはこのURLへブラウザから直接PUTするため、
# 発行先のホストはCloudFrontのCSP connect-src(設計書9.2)と一致させる必要がある
_PRESIGN_CONFIG = Config(signature_version="s3v4", s3={"addressing_style": "virtual"})


class DocumentStorage:
    """DocumentsバケットのPresigned URLを発行する。"""

    def __init__(self, bucket_name: str) -> None:
        self._bucket_name = bucket_name
        self._client = boto3.client("s3", config=_PRESIGN_CONFIG)

    def presign_put(self, key: str, content_type: str | None = None) -> str:
        params: dict = {"Bucket": self._bucket_name, "Key": key}
        # ContentTypeを署名に含めることで、発行時と異なるContent-Typeでのアップロードを拒否する
        if content_type:
            params["ContentType"] = content_type
        return self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=UPLOAD_URL_EXPIRES_IN
        )

    def delete_object(self, key: str) -> None:
        """存在しないキーを指定してもS3はエラーを返さないため、削除の再実行は安全に行える。"""
        self._client.delete_object(Bucket=self._bucket_name, Key=key)

    def presign_get(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket_name, "Key": key},
            ExpiresIn=DOWNLOAD_URL_EXPIRES_IN,
        )
