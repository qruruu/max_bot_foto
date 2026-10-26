import InspectionChats from './Chats';
import { OrganizationQR } from './QR';
import './inspection.css';

export default function InspectionAdministration() {
  return <><header className="page-header"><div><h1>Проверяющие</h1><p>Одноразовые QR доступа к организации и личные чаты с проверяющими.</p></div></header>
    <OrganizationQR endpoint="/inspection-admin/qr"/><InspectionChats base="/inspection-admin"/></>;
}
