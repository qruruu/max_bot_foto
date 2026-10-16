import { Moon, Sun } from 'lucide-react';
import { useTheme } from './theme';

export default function ThemeSettings() {
  const {theme, setTheme} = useTheme();
  const dark = theme === 'dark';
  return <section className="panel account-appearance" aria-labelledby="appearance-title">
    <h2 id="appearance-title">Оформление</h2>
    <div className="appearance-row">
      <div>
        <strong id="dark-theme-label">Тёмная тема</strong>
        <p id="dark-theme-description" className="hint">{dark ? 'Включена' : 'Выключена'}</p>
      </div>
      <button className="theme-switch" type="button" role="switch" aria-checked={dark}
        aria-labelledby="dark-theme-label" aria-describedby="dark-theme-description"
        onClick={() => setTheme(dark ? 'light' : 'dark')}>
        <span className="theme-switch-thumb" aria-hidden="true">{dark ? <Moon size={14}/> : <Sun size={14}/>}</span>
      </button>
    </div>
    <p className="hint appearance-note">Тема применяется ко всем разделам. Выбор сохраняется в этом браузере.</p>
  </section>;
}
