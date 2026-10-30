import 'dart:typed_data';
import 'package:signal_citizens/models.dart';

const organizationId = '11111111-1111-4111-8111-111111111111';
const addressId = '22222222-2222-4222-8222-222222222222';
final polygon = <String, dynamic>{
  'type': 'Polygon',
  'coordinates': [
    [
      [72, 61],
      [73, 61],
      [73, 62],
      [72, 62],
      [72, 61],
    ],
    [
      [72.7, 61.7],
      [72.8, 61.7],
      [72.8, 61.8],
      [72.7, 61.8],
      [72.7, 61.7],
    ],
  ],
};
final catalogJson = <String, dynamic>{
  'yandex_maps_api_key': '',
  'organizations': [
    {
      'id': organizationId,
      'name': 'ИП Шашко',
      'city': 'Нефтеюганск',
      'color': '#195c46',
      'addresses': [
        {'id': addressId, 'label': '12 мкр', 'district_id': 1},
      ],
      'territories': [
        {'id': 1, 'name': '12 мкр', 'geometry': polygon},
      ],
    },
  ],
};
final appealJson = <String, dynamic>{
  'id': 7,
  'number': 'ОБ-000007',
  'subject': 'Не убрана детская площадка',
  'description': 'На площадке много листьев и мусора. Просим провести уборку.',
  'status': 'NEW',
  'address': '12 мкр',
  'place': '',
  'organization_name': 'ИП Шашко',
  'created_at': '2026-10-30T04:25:00Z',
  'photos': [],
  'response': null,
};
final emptyWall = <String, dynamic>{
  'items': [],
  'total': 0,
  'page': 1,
  'page_size': 20,
};
LocalPhoto photo() => LocalPhoto(
  id: 'photo-1',
  name: 'photo.jpg',
  mime: 'image/jpeg',
  bytes: Uint8List.fromList([1, 2, 3]),
  preview: Uint8List.fromList([1, 2, 3]),
);
AppealForm validForm() => AppealForm(
  city: 'Нефтеюганск',
  organizationId: organizationId,
  addressId: addressId,
  address: '12 мкр',
  longitude: 72.6,
  latitude: 61.1,
  subject: 'Не убрана детская площадка',
  description: 'Много листьев и мусора',
);
