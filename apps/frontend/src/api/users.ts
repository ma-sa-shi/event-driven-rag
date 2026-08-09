import type { ChatSummary } from "./chats";
import { api } from "./client";
import type { DocumentSummary } from "./documents";

/** サインイン時にCognitoから同期したプロフィール。マスタはCognito側にある。 */
export interface UserProfile {
  userId: string;
  displayName: string;
  email: string;
  createdAt: string;
  updatedAt: string;
}

export async function fetchUser(userId: string): Promise<UserProfile> {
  const res = await api.get<UserProfile>(`/users/${userId}`);
  return res.data;
}

export async function listUserChats(userId: string): Promise<ChatSummary[]> {
  const res = await api.get<ChatSummary[]>(`/users/${userId}/chats`);
  return res.data;
}

export async function listUserDocuments(
  userId: string,
): Promise<DocumentSummary[]> {
  const res = await api.get<DocumentSummary[]>(`/users/${userId}/documents`);
  return res.data;
}
