import { useState } from 'react';
import OwnerAppeals from '../appeals/OwnerAppeals';
import InspectionAppealForm from './AppealForm';

export default function InspectionAppeals({organizationId, inspectorId, refreshKey}: {organizationId: string; inspectorId: number; refreshKey: number}) {
  const [creating, setCreating] = useState(false), [revision, setRevision] = useState(0);
  return <OwnerAppeals organization endpoint={'/inspection/organizations/' + organizationId + '/appeals'} readOnly refreshKey={refreshKey + revision}
    onCreate={() => setCreating(true)}
    composer={creating ? <InspectionAppealForm key={inspectorId + ':' + organizationId} organizationId={organizationId} inspectorId={inspectorId} created={() => {
      setRevision(value => value + 1); window.dispatchEvent(new Event('appeals-changed')); window.dispatchEvent(new Event('refresh-appeals'));
    }}/> : undefined}/>;
}
