import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import { inspectionMapFeature, loadInspectionMap } from './Maps';
import type { InspectionPhoto } from './types';

vi.mock('../api', async importOriginal => ({...await importOriginal<typeof import('../api')>(),api:vi.fn()}));
afterEach(()=>vi.mocked(api).mockReset());
const photo={id:10,latitude:61.1,longitude:72.5,received_at:'2026-10-25T12:00:00Z',photo_date:'2026-10-25',
  photo_time:'12:00:00',preview_url:'/api/inspection/organizations/org/photos/10/preview',district_name:'<script>district</script>',
  work_type_name:'Уборка',chat_name:'hidden-chat',sender_id:'hidden-sender',work_type_source:'AI'} as unknown as InspectionPhoto;

it('loads every map batch using the original snapshot and filters without the table page limit',async()=>{
  vi.mocked(api).mockResolvedValueOnce({items:[photo],summary:{total:2,located:2,without_coordinates:0},snapshot_id:50,next_after_id:10})
    .mockResolvedValueOnce({items:[{...photo,id:20}],summary:null,snapshot_id:50,next_after_id:null});
  const progress=vi.fn();const result=await loadInspectionMap('/inspection/organizations/org','work_type=CLEAN',new AbortController().signal,progress);
  expect(result.items.map(p=>p.id)).toEqual([10,20]);
  expect(vi.mocked(api).mock.calls[1][0]).toContain('after_id=10');
  expect(vi.mocked(api).mock.calls[1][0]).toContain('snapshot_id=50');
  expect(vi.mocked(api).mock.calls[1][0]).toContain('work_type=CLEAN');
  expect(progress).toHaveBeenLastCalledWith(2);
});

it('escapes map labels and never includes operator, sender, chat or classification data',()=>{
  const feature=inspectionMapFeature(photo,'/inspection?tab=photo-map&photo=10');
  expect(feature.geometry.coordinates).toEqual([72.5,61.1]);
  expect(feature.properties.photoPreviewUrl).toBe(photo.preview_url);
  expect(feature.properties.balloonContentBody).toContain('data-photo-id="10"');
  for(const hidden of ['<script>','hidden-chat','hidden-sender','work_type_source','Нейросеть'])expect(JSON.stringify(feature)).not.toContain(hidden);
});

it('rejects a stalled cursor instead of looping indefinitely',async()=>{
  vi.mocked(api).mockResolvedValue({items:[],summary:{total:2,located:2,without_coordinates:0},snapshot_id:50,next_after_id:0});
  await expect(loadInspectionMap('/inspection/organizations/org','',new AbortController().signal,()=>{})).rejects.toThrow('Обновите карту');
  expect(api).toHaveBeenCalledTimes(1);
});
