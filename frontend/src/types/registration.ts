/**
 * Статус заявки на регистрацию.
 */
export type RegistrationStatus = "pending" | "approved" | "rejected" | "cancelled";

/**
 * Данные для создания заявки на регистрацию.
 */
export interface RegistrationCreateRequest {
  email: string;
  username: string;
  password: string;
}

/**
 * Представление заявки на регистрацию.
 */
export interface RegistrationRead {
  id: string;
  email: string;
  username: string;
  status: RegistrationStatus;
  comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

/**
 * Данные для одобрения заявки на регистрацию.
 */
export interface RegistrationApproveRequest {
  comment?: string | null;
}

/**
 * Ответ API после одобрения заявки на регистрацию.
 */
export interface RegistrationApproveResponse {
  request: RegistrationRead;
  created_user_id: string | null;
}

/**
 * Данные для отклонения заявки на регистрацию.
 */
export interface RegistrationRejectRequest {
  rejection_reason: string;
  comment?: string | null;
}
