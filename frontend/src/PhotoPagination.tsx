import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function PhotoPagination({page, pageSize, total, onPageChange, position}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  position: 'top' | 'bottom';
}) {
  const lastPage = Math.ceil(total / pageSize);
  if (lastPage <= 1) return null;

  return <nav className={'pagination photo-pagination-' + position} aria-label={position === 'top' ? 'Страницы фотографий сверху' : 'Страницы фотографий снизу'}>
    <span>Страница {page} из {lastPage}</span>
    <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft size={16}/>Назад</button>
    <button type="button" disabled={page >= lastPage} onClick={() => onPageChange(page + 1)}>Далее<ChevronRight size={16}/></button>
  </nav>;
}
