import type { RefObject } from 'react';
import { Menu } from 'lucide-react';
import { useOperatorChats } from './OperatorChatsProvider';

export default function MobileNavigation({button, open, toggle, updates = false}: {
  button: RefObject<HTMLButtonElement | null>; open: boolean; toggle: () => void; updates?: boolean;
}) {
  const chats = useOperatorChats();
  const hasUpdates = updates || (chats?.unread ?? 0) > 0;
  return <button ref={button} type="button" className="mobile-navigation-button" onClick={toggle}
    aria-label={hasUpdates ? 'Меню, есть обновления' : 'Меню'} aria-expanded={open} aria-controls="workspace-sidebar">
    <Menu size={20}/>{hasUpdates && <span aria-hidden="true"/>}
  </button>;
}
