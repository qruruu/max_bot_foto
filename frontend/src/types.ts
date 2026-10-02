export type User = { id: number; login: string; name: string; role: string; active: boolean };
export type Chat = { id: number; max_chat_id: number; name: string; active: boolean };
export type District = { id: number; name: string; active: boolean };
export type Meta = { yandex_maps_api_key: string; today: string; timezone: string; work_types: { code: string; name: string }[]; statuses: string[]; chats: Chat[]; districts: District[]; operators: { id: number; name: string }[] };
export type Filters = Record<string, string>;
export type Audit = {id: number; user_id: number | null; at: string; action: string; object_type: string; object_id: number; old_value: unknown; new_value: unknown};
export type Photo = {
  id: number; version: number; status: string; storage_status: string; photo_date: string | null; photo_time: string | null;
  received_at: string; latitude: number | null; longitude: number | null; chat_name: string; district_id: number | null;
  district_name: string | null; work_type: string | null; work_type_name: string | null; ai_confidence: number | null;
  ai_alternatives: string[]; review_reason: string[]; detected_address: string | null; detected_city: string | null;
  max_message_id: string; yandex_disk_path: string | null; operator_name: string | null; preview_url: string | null;
  processing_error: string | null; ai_result: unknown; ocr_raw_text: string | null; analyzed_at: string | null;
  history: Audit[]; work_type_source: string | null;
};
export type PhotoPage = { items: Photo[]; total: number; page: number; page_size: number };
export type Breakdown = { id: string | number; name: string; count: number };
export type Report = { total: number; accepted: number; counts: Record<string, number>; chats: Breakdown[]; districts: Breakdown[]; work_types: Breakdown[]; matrix: { chat_id: number; district_id: number; count: number }[] };
