import { Bell, Volume2 } from 'lucide-react';
import { usePhotoNotifications } from './PhotoNotifications';

export default function NotificationSettings() {
  const {preferences, setPreference, canViewPhotos} = usePhotoNotifications();
  return <section className="panel account-notifications" aria-labelledby="notifications-title">
    <h2 id="notifications-title">Новые фотографии</h2>
    {(['popup', 'sound'] as const).map(key => <div className="appearance-row notification-setting" key={key}>
      <div><strong id={`notification-${key}-label`}>{key === 'popup' ? 'Уведомления на экране' : 'Звуковой сигнал'}</strong>
        <p className="hint" id={`notification-${key}-description`}>{key === 'popup' ? 'Сообщение в правом верхнем углу' : 'Короткий сигнал при поступлении снимков'}</p>
      </div>
      <button className="theme-switch" type="button" role="switch" aria-checked={preferences[key]} disabled={!canViewPhotos}
        aria-labelledby={`notification-${key}-label`} aria-describedby={`notification-${key}-description`}
        onClick={() => setPreference(key, !preferences[key])}>
        <span className="theme-switch-thumb" aria-hidden="true">{key === 'popup' ? <Bell size={13}/> : <Volume2 size={13}/>}</span>
      </button>
    </div>)}
    <p className="hint appearance-note">{canViewPhotos
      ? 'Работают, пока сервис открыт в браузере. Звук включается после первого нажатия на странице. Выбор сохраняется для вас в этом браузере.'
      : 'Уведомления доступны пользователям с правом просмотра фотографий.'}</p>
  </section>;
}
