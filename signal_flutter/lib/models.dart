import 'dart:convert';
import 'dart:typed_data';

typedef Json = Map<String, dynamic>;

class Organization {
  Organization(this.json);
  final Json json;
  String get id => json['id'] as String;
  String get name => json['name'] as String;
  String get city => json['city'] as String;
  String get color => json['color'] as String? ?? '#195c46';
  List<Json> get addresses => List<Json>.from(json['addresses'] as List? ?? []);
  List<Json> get territories =>
      List<Json>.from(json['territories'] as List? ?? []);
}

class Catalog {
  Catalog.fromJson(Json json)
    : organizations = (json['organizations'] as List)
          .map((item) => Organization(Json.from(item as Map)))
          .toList(),
      mapKey = json['yandex_maps_api_key'] as String? ?? '';
  final List<Organization> organizations;
  final String mapKey;
  List<String> get cities =>
      (organizations.map((item) => item.city).toSet().toList()..sort());
}

class AppealPhoto {
  AppealPhoto.fromJson(Json json)
    : id = json['id'].toString(),
      url = json['url'] as String,
      previewUrl = json['preview_url'] as String;
  final String id, url, previewUrl;
}

class PublicResponse {
  PublicResponse.fromJson(Json json)
    : comment = json['comment'] as String,
      at = DateTime.parse(json['at'] as String),
      photos = photoList(json['photos']);
  final String comment;
  final DateTime at;
  final List<AppealPhoto> photos;
}

List<AppealPhoto> photoList(dynamic value) => (value as List? ?? [])
    .map((item) => AppealPhoto.fromJson(Json.from(item as Map)))
    .toList();

class Appeal {
  Appeal.fromJson(Json json)
    : id = json['id'] as int,
      number = json['number'] as String,
      subject = json['subject'] as String? ?? '',
      description = json['description'] as String,
      status = json['status'] as String,
      address = json['address'] as String,
      place = json['place'] as String? ?? '',
      organization = json['organization_name'] as String,
      createdAt = DateTime.parse(json['created_at'] as String),
      shareUrl = json['share_url'] as String?,
      photos = photoList(json['photos']),
      response = json['response'] == null
          ? null
          : PublicResponse.fromJson(Json.from(json['response'] as Map));
  final int id;
  final String number,
      subject,
      description,
      status,
      address,
      place,
      organization;
  final String? shareUrl;
  final DateTime createdAt;
  final List<AppealPhoto> photos;
  final PublicResponse? response;
}

class WallPage {
  WallPage.fromJson(Json json)
    : items = (json['items'] as List)
          .map((item) => Appeal.fromJson(Json.from(item as Map)))
          .toList(),
      total = json['total'] as int,
      page = json['page'] as int,
      pageSize = json['page_size'] as int;
  final List<Appeal> items;
  final int total, page, pageSize;
  int get pages => (total / pageSize).ceil().clamp(1, 1000000);
}

class LocalPhoto {
  LocalPhoto({
    required this.id,
    required this.name,
    required this.mime,
    required this.bytes,
    required this.preview,
    this.capture,
  });
  factory LocalPhoto.fromJson(Json json) => LocalPhoto(
    id: json['id'] as String,
    name: json['name'] as String? ?? 'photo.jpg',
    mime: json['mime'] as String? ?? 'image/jpeg',
    bytes: base64Decode(json['data'] as String),
    preview: base64Decode(json['preview'] as String),
    capture: json['capture'] as Json?,
  );
  final String id, name, mime;
  final Uint8List bytes, preview;
  final Json? capture;
  late final String _data64 = base64Encode(bytes);
  late final String _preview64 = identical(bytes, preview)
      ? _data64
      : base64Encode(preview);
  Json toJson() => {
    'id': id,
    'name': name,
    'mime': mime,
    'data': _data64,
    'preview': _preview64,
    if (capture != null) 'capture': capture,
  };
}

class AppealForm {
  AppealForm({
    this.city = '',
    this.organizationId = '',
    this.addressId = '',
    this.address = '',
    this.subject = '',
    this.description = '',
    this.place = '',
    this.contact = '',
    this.website = '',
    this.latitude,
    this.longitude,
  });
  factory AppealForm.fromJson(Json json) => AppealForm(
    city: json['city'] as String? ?? '',
    organizationId: json['organization_id'] as String? ?? '',
    addressId: json['address_id'] as String? ?? '',
    address: json['address'] as String? ?? '',
    subject: json['subject'] as String? ?? '',
    description: json['description'] as String? ?? '',
    place: json['place'] as String? ?? '',
    contact: json['contact'] as String? ?? '',
    website: json['website'] as String? ?? '',
    latitude: (json['latitude'] as num?)?.toDouble(),
    longitude: (json['longitude'] as num?)?.toDouble(),
  );
  String city,
      organizationId,
      addressId,
      address,
      subject,
      description,
      place,
      contact,
      website;
  double? latitude, longitude;
  bool get located =>
      addressId.isNotEmpty && latitude != null && longitude != null;
  bool get hasText =>
      subject.trim().isNotEmpty || description.trim().isNotEmpty;
  Json toJson() => {
    'city': city,
    'organization_id': organizationId,
    'address_id': addressId,
    'address': address,
    'subject': subject,
    'description': description,
    'place': place,
    'contact': contact,
    'website': website,
    'category': '',
    'latitude': latitude,
    'longitude': longitude,
  };
}

class AppealDraft {
  AppealDraft({
    required this.form,
    required this.photos,
    this.token,
    this.pending = false,
    this.receipt,
    DateTime? savedAt,
  }) : savedAt = savedAt ?? DateTime.now();
  factory AppealDraft.fromJson(Json json) => AppealDraft(
    form: AppealForm.fromJson(Json.from(json['form'] as Map)),
    photos: (json['photos'] as List? ?? [])
        .map((item) => LocalPhoto.fromJson(Json.from(item as Map)))
        .toList(),
    token: json['token'] as String?,
    pending: json['pending'] as bool? ?? false,
    receipt: json['receipt'] as String?,
    savedAt: DateTime.fromMillisecondsSinceEpoch(
      (json['savedAt'] as num).toInt(),
    ),
  );
  final AppealForm form;
  final List<LocalPhoto> photos;
  final String? token, receipt;
  final bool pending;
  final DateTime savedAt;
  bool get hasContent => form.hasText || photos.isNotEmpty || pending;
  Json toJson() => {
    'form': form.toJson(),
    'photos': photos.map((p) => p.toJson()).toList(),
    'token': token,
    'pending': pending,
    'savedAt': savedAt.millisecondsSinceEpoch,
    if (receipt != null) 'receipt': receipt,
  };
}

const appealStatuses = <String, String>{
  'NEW': 'Новое',
  'IN_REVIEW': 'На рассмотрении',
  'ASSIGNED': 'Назначен исполнитель',
  'IN_PROGRESS': 'В работе',
  'COMPLETED': 'На проверке результата',
  'REJECTED': 'Исполнитель отклонил',
  'CANCELLED': 'Задача отменена',
  'RESOLVED': 'Закрыто',
  'DECLINED': 'Отказ',
  'SPAM': 'Спам',
};

String formatDate(DateTime value, {bool time = false}) {
  final date = value.toLocal();
  String two(int value) => value.toString().padLeft(2, '0');
  return '${two(date.day)}.${two(date.month)}.${date.year}'
      '${time ? ', ${two(date.hour)}:${two(date.minute)}' : ''}';
}

/// Match PostGIS ST_Covers: include boundaries and exclude hole interiors.
bool coversPoint(Json geometry, double longitude, double latitude) {
  if (!longitude.isFinite || !latitude.isFinite) return false;
  final polygons = geometry['type'] == 'Polygon'
      ? [geometry['coordinates'] as List]
      : geometry['coordinates'] as List;
  int ringPosition(List ring) {
    var inside = false;
    for (int i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      final a = ring[j] as List, b = ring[i] as List;
      final ax = (a[0] as num).toDouble(), ay = (a[1] as num).toDouble();
      final bx = (b[0] as num).toDouble(), by = (b[1] as num).toDouble();
      final cross = (longitude - ax) * (by - ay) - (latitude - ay) * (bx - ax);
      if (cross.abs() < 1e-12 &&
          longitude >= (ax < bx ? ax : bx) &&
          longitude <= (ax > bx ? ax : bx) &&
          latitude >= (ay < by ? ay : by) &&
          latitude <= (ay > by ? ay : by)) {
        return 0;
      }
      if ((ay > latitude) != (by > latitude) &&
          longitude < (bx - ax) * (latitude - ay) / (by - ay) + ax) {
        inside = !inside;
      }
    }
    return inside ? 1 : -1;
  }

  return polygons.any((value) {
    final rings = value as List;
    return rings.isNotEmpty &&
        ringPosition(rings.first as List) >= 0 &&
        !rings.skip(1).any((hole) => ringPosition(hole as List) > 0);
  });
}
