import { Link, useSearchParams, Navigate } from 'react-router-dom';
import { OrganizationQR } from './QR';
import './inspection.css';

export default function InspectionAdministration() {
  const [params] = useSearchParams();
  if (params.has('with')) return <Navigate to={'/messages?' + new URLSearchParams({with: params.get('with') || ''})} replace/>;
  return <><header className="page-header"><div><h1>Проверяющие</h1><p>Доступ к организации по QR.</p></div></header>
    <OrganizationQR endpoint="/inspection-admin/qr"/><Link className="button" to="/messages">Открыть чаты</Link></>;
}
