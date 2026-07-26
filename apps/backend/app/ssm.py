"""SSM Parameter StoreのSecureString取得。

APIキーはCloudFormationで作成できないためパラメータ本体は手動作成し、
Lambdaへはパラメータ名だけを環境変数で渡す(ADR-0008)。値はここで解決する。
"""

from functools import lru_cache

import boto3


# Lambda実行環境が生きている限り再取得しない(呼び出し回数と初期化レイテンシの削減)
@lru_cache
def get_parameter(name: str) -> str:
    res = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)
    return res["Parameter"]["Value"]
