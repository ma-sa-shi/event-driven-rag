import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getChat } from "../api/chats";
import { ChatProgress } from "../components/ChatProgress";
import { GradeBadge } from "../components/GradeBadge";
import { toAttempt } from "../lib/chatProgress";
import { isNotFound, toErrorMessage } from "../lib/errors";
import { useOpenDocument } from "../lib/useOpenDocument";
import "./ChatDetail.css";

const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "short",
  timeStyle: "short",
});

export function ChatDetail() {
  const params = useParams();
  // ルート定義上chatIdは必ず入る
  const chatId = params.chatId!;
  const [error, setError] = useState<string | null>(null);
  const { openDocument, openingId } = useOpenDocument(setError);

  const chatQuery = useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => getChat(chatId),
  });

  const handleOpen = (documentId: string) => {
    setError(null);
    void openDocument(documentId);
  };

  const chat = chatQuery.data;

  return (
    <div className="chat-detail">
      <h1 className="page-title">チャット詳細</h1>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {chatQuery.isPending && <p className="placeholder">読み込み中…</p>}

      {chatQuery.isError &&
        (isNotFound(chatQuery.error) ? (
          <p className="placeholder">
            チャットが見つかりません <Link to="/">チャット一覧へ戻る</Link>
          </p>
        ) : (
          <p className="placeholder">
            {toErrorMessage(chatQuery.error, "チャットを取得できませんでした")}{" "}
            <button type="button" onClick={() => void chatQuery.refetch()}>
              再試行
            </button>
          </p>
        ))}

      {chat && (
        <>
          <section className="chat-question-block">
            <div className="chat-question-head">
              <h2>質問</h2>
              <Link to={`/user/${chat.userId}`}>質問者のページ</Link>
            </div>
            <p className="chat-question-body">{chat.question}</p>
            <time className="chat-question-time" dateTime={chat.createdAt}>
              {dateFormatter.format(new Date(chat.createdAt))}
            </time>
          </section>

          {chat.finalAnswer !== null && (
            <section className="final-answer">
              <div className="final-answer-head">
                <h2>回答</h2>
                {chat.finalGrade && <GradeBadge grade={chat.finalGrade} />}
              </div>
              <p className="final-answer-body">{chat.finalAnswer}</p>
              {/* 評価がusefulに達しない場合、バックエンドは必ず1回再試行してから終える */}
              {chat.finalGrade && chat.finalGrade !== "useful" && (
                <p className="final-answer-note">
                  再試行しても自己評価が「有用」に達しませんでした。取り込み済みのドキュメントに根拠が無い可能性があります。
                </p>
              )}
            </section>
          )}

          <h2 className="attempts-title">試行の記録</h2>
          <ChatProgress
            attempts={chat.attempts.map(toAttempt)}
            isStreaming={false}
            showAnswerBody
            onOpenDocument={handleOpen}
          />
          {openingId && <p className="placeholder">原本を開いています…</p>}
        </>
      )}
    </div>
  );
}
