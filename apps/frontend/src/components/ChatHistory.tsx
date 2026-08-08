import { Link } from "react-router-dom";
import type { ChatSummary } from "../api/chats";
import { GradeBadge } from "./GradeBadge";
import "./ChatHistory.css";

interface ChatHistoryProps {
  chats: ChatSummary[];
  currentUserId: string | undefined;
}

const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "short",
  timeStyle: "short",
});

export function ChatHistory({ chats, currentUserId }: ChatHistoryProps) {
  return (
    <ul className="chat-history">
      {chats.map((chat) => (
        <li key={chat.chatId}>
          {/* 詳細画面(/chat/:chatId)はIssue #18で実装する */}
          <Link className="chat-history-item" to={`/chat/${chat.chatId}`}>
            <span className="chat-question">{chat.question}</span>
            <span className="chat-meta">
              {chat.finalGrade && <GradeBadge grade={chat.finalGrade} />}
              {chat.retryCount > 0 && (
                <span className="chat-retry">再試行{chat.retryCount}回</span>
              )}
              {chat.userId === currentUserId && (
                <span className="chat-mine">自分</span>
              )}
              <time dateTime={chat.createdAt}>
                {dateFormatter.format(new Date(chat.createdAt))}
              </time>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
