import boto3

# presigned URLはLambdaロールで署名されるため、実行ロールに対象操作の権限が必要
# 長すぎるとURL漏洩時のリスクが増すため15分に制限
UPLOAD_URL_EXPIRES_IN = 900
DOWNLOAD_URL_EXPIRES_IN = 900


class DocumentStorage:
    """DocumentsバケットのPresigned URLを発行する。"""

    def __init__(self, bucket_name: str) -> None:
        self._bucket_name = bucket_name
        self._client = boto3.client("s3")

    def presign_put(self, key: str, content_type: str | None = None) -> str:
        params: dict = {"Bucket": self._bucket_name, "Key": key}
        # ContentTypeを署名に含めることで、発行時と異なるContent-Typeでのアップロードを拒否する
        if content_type:
            params["ContentType"] = content_type
        return self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=UPLOAD_URL_EXPIRES_IN
        )

    def presign_get(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket_name, "Key": key},
            ExpiresIn=DOWNLOAD_URL_EXPIRES_IN,
        )
