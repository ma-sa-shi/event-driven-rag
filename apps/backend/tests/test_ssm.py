import boto3
from moto import mock_aws

from app.ssm import get_parameter

PARAMETER_NAME = "/event-driven-rag/test-key"


def test_get_parameter_decrypts_secure_string_and_caches():
    """get_parameter が SecureString を復号して取得できること、およびキャッシュ(lru_cache)が正しく機能するか"""
    with mock_aws():
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name=PARAMETER_NAME, Value="secret-1", Type="SecureString")

        # テスト実行前の安全策としてキャッシュを初期化
        get_parameter.cache_clear()

        # 初回取得の検証
        assert get_parameter(PARAMETER_NAME) == "secret-1"

        # キャッシュ機能の検証
        # SSM側の値を更新しても、関数キャッシュが効いているため初回取得の値(secret-1)が返ること
        ssm.put_parameter(
            Name=PARAMETER_NAME, Value="secret-2", Type="SecureString", Overwrite=True
        )
        assert get_parameter(PARAMETER_NAME) == "secret-1"

        # キャッシュ破棄後の再取得検証
        # キャッシュをクリアした後は、再度SSMから最新の値(secret-2)が取得できること
        get_parameter.cache_clear()
        assert get_parameter(PARAMETER_NAME) == "secret-2"
