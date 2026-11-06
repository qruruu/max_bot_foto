import { useEffect, useState } from 'react';
import { api } from '../api';
import OwnerAppeals from '../appeals/OwnerAppeals';
import InspectionAppealForm from './AppealForm';

export default function InspectionAppeals({organizationId, inspectorId, refreshKey}: {organizationId: string; inspectorId: number; refreshKey: number}) {
  const [creating, setCreating] = useState(false), [revision, setRevision] = useState(0);
  const [administrators, setAdministrators] = useState<string[]>([]);
  const endpoint = '/inspection/organizations/' + organizationId + '/appeals';
  useEffect(() => {
    const controller = new AbortController();
    setAdministrators([]);
    api<string[]>(endpoint + '/recipients', 'GET', undefined, controller.signal)
      .then(names => {if (!controller.signal.aborted) setAdministrators(names);}).catch(() => {});
    return () => controller.abort();
  }, [endpoint]);
  return <OwnerAppeals organization endpoint={endpoint} readOnly administrators={administrators} refreshKey={refreshKey + revision}
    onCreate={() => setCreating(true)}
    composer={creating ? <InspectionAppealForm key={inspectorId + ':' + organizationId} organizationId={organizationId} inspectorId={inspectorId} administrators={administrators} onClose={() => setCreating(false)} created={() => {
      setRevision(value => value + 1); window.dispatchEvent(new Event('appeals-changed')); window.dispatchEvent(new Event('refresh-appeals'));
    }}/> : undefined}/>;
}
