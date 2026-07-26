"""
Self-RAGの4つのプロンプト定義。

【設計上の注意点】
'generate_queries_prompt' の '{feedback}' は、テンプレート側ではなく値側が'フィードバック:'という接頭辞を持つ
これにより、初回試行時に、空の見出し'フィードバック:'がプロンプトに残るのを防ぎ、LLMへのノイズを回避している
"""

from langchain_core.prompts import ChatPromptTemplate

# クエリ生成プロンプト
# feedbackはgrade_answer_nodeからのフィードバックが入る。最初の試行では空文字列が入る
generate_queries_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "あなたは検索の専門家です。ユーザーの質問を解決するために、ベクトルストアから必要な情報を引き出す検索クエリを生成してください。\n"
            "【クエリ生成の方針】\n"
            "質問の表面的な言葉を繰り返すだけでなく、類義語、上位/下位概念を組み合わせること。\n"
            "前回の試行に対するフィードバックがある場合は、それを踏まえて異なるアプローチのクエリを生成すること。",
        ),
        ("human", "質問: {question}\n{feedback}"),
    ]
)

# 回答生成プロンプト
generate_answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "あなたは提供されたコンテキストのみに基づいて回答する専門家です。\n\n"
            "【回答生成の方針】\n"
            "コンテキストだけを踏まえて質問に対する回答を生成すること。\n"
            "コンテキストから判断できない場合は、'コンテキストからは回答できません'と回答すること。\n"
            "コンテキスト: {context}",
        ),
        ("human", "質問: {question}"),
    ]
)

# 回答評価プロンプト
grade_answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "あなたは提供されたコンテキストを基に、回答の品質を評価する専門家です。\n\n"
            "【評価基準】\n"
            "- useful: 回答が正確で、質問に対して十分に答えている。\n"
            "- useless: 回答にハルシネーションはないが、情報が不足している、または'コンテキストからは回答できません'と答えている。\n"
            "- hallucination: 回答に、コンテキストに含まれていない事実や嘘が含まれている。\n\n"
            "【フィードバックの方針】"
            "評価が'useless'または'hallucination'の場合は、コンテキストのどこが足りないか、どの表現がハルシネーションに該当するかを指摘すること。\n\n"
            "コンテキスト: {context}",
        ),
        ("human", "質問: {question}\n\n回答: {answer}"),
    ]
)

# 失敗分析プロンプト
analyze_failure_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "あなたはRAGシステムを分析する専門家です。ユーザーの質問に対して十分な回答が得られなかった原因を分析してください。\n"
            "【分析の方針】\n"
            "ベクトルストアに必要な情報が存在しない。\n"
            "ユーザーの質問が曖昧すぎて、検索クエリの絞り込みができなかった。\n"
            "初回のクエリが適切ではなく、必要な情報を引き出せなかった。\n"
            "その他（具体的に記述してください）",
        ),
        (
            "human",
            "### 分析データ\n"
            "ユーザーの質問: {question}\n"
            "初回のクエリ: {initial_queries}\n"
            "初回のコンテキスト: {initial_context}\n"
            "初回の回答へのフィードバック: {initial_feedback}\n"
            "再試行後の回答へのフィードバック: {retry_feedback}",
        ),
    ]
)
