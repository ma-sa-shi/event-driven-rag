import { Template } from 'aws-cdk-lib/assertions';

// CDKのアセットハッシュはソース内容から算出される為、backendを1行直すだけで
// ImageUriが変わり、無関係なスナップショットが落ちる。
// 対象はコンテナイメージのImageUri、Lambdaアセットの<hash>.zip、aws:asset:pathメタデータで、
// いずれも64桁の16進数として現れる。CDKテンプレート中の他の値がこの形になることはない
const ASSET_HASH_PATTERN = /\b[0-9a-f]{64}\b/g;
const ASSET_HASH_PLACEHOLDER = '<ASSET_HASH>';

function replaceHashes(value: unknown): unknown {
  if (typeof value === 'string') {
    return value.replace(ASSET_HASH_PATTERN, ASSET_HASH_PLACEHOLDER);
  }
  if (Array.isArray(value)) {
    return value.map(replaceHashes);
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, replaceHashes(child)]),
    );
  }
  return value;
}

/**
 * アセットハッシュを固定文字列へ置換したテンプレートを返す。
 * Templateインスタンスは他のアサーションと共有される為、複製してから置換する。
 */
export function normalizeAssetHashes(template: Template): unknown {
  return replaceHashes(template.toJSON());
}
