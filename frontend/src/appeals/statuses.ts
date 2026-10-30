export const appealStatuses: Record<string, string> = {
  NEW: 'Новое', IN_REVIEW: 'На рассмотрении', ASSIGNED: 'Назначен исполнитель', IN_PROGRESS: 'В работе',
  COMPLETED: 'На проверке результата', REJECTED: 'Исполнитель отклонил', CANCELLED: 'Задача отменена',
  RESOLVED: 'Закрыто', DECLINED: 'Отказ', SPAM: 'Спам',
};

type AppealState = {status: string; is_final?: boolean; resolved_at?: string | null};
export const hasAppealDecision = (appeal: AppealState) => ['RESOLVED', 'DECLINED'].includes(appeal.status)
  || ['CANCELLED', 'REJECTED'].includes(appeal.status) && (appeal.is_final === true || !!appeal.resolved_at);
export const isFinalAppeal = (appeal: AppealState) => appeal.is_final ?? (appeal.status === 'SPAM' || hasAppealDecision(appeal));

export const appealDecisions: Record<string, {label: string; verb: string; confirm: string; question: string}> = {
  RESOLVED: {label: 'Закрыть обращение', verb: 'Закрыть', confirm: 'Подтвердить закрытие', question: 'Закрыть обращение?'},
  DECLINED: {label: 'Отказ', verb: 'Отказать', confirm: 'Подтвердить отказ', question: 'Отказать по обращению?'},
  CANCELLED: {label: 'Задача отменена', verb: 'Отменить', confirm: 'Подтвердить отмену', question: 'Завершить обращение со статусом «Задача отменена»?'},
  REJECTED: {label: 'Исполнитель отклонил', verb: 'Отклонить', confirm: 'Подтвердить отклонение', question: 'Завершить обращение со статусом «Исполнитель отклонил»?'},
};
