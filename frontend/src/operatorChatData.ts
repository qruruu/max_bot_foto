export type OperatorMessage = {
  id: number; sender_id: number; recipient_id: number; client_id: string;
  body: string; created_at: string; read_at: string | null;
};
export type OperatorContact = {
  id: number; name: string; role: string; active: boolean; avatar_url: string | null;
  unread: number; last_message: OperatorMessage | null;
};
export type ContactPage = {items: OperatorContact[]; unread: number};
export type MessagePage = {
  items: OperatorMessage[]; has_older: boolean; has_newer: boolean; peer_read_through_id: number;
};

export function mergeMessages(current: OperatorMessage[], incoming: OperatorMessage[]) {
  const byId = new Map(current.map(message => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((left, right) => left.id - right.id);
}

export function messageTime(value: string, timezone: string) {
  return new Date(value).toLocaleTimeString('ru-RU', {timeZone: timezone, hour: '2-digit', minute: '2-digit'});
}

export function messageDay(value: string, timezone: string) {
  return new Date(value).toLocaleDateString('ru-RU', {timeZone: timezone, day: 'numeric', month: 'long', year: 'numeric'});
}
