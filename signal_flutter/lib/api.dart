import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'models.dart';

class AppealRequestError implements Exception {
  AppealRequestError(this.message, [this.status = 0]);
  final String message;
  final int status;
  bool get uncertain => status == 0 || status >= 500;
  @override
  String toString() => message;
}

class SignalApi {
  SignalApi({required this.origin, http.Client? client})
    : client = client ?? http.Client();
  final Uri origin;
  final http.Client client;
  Uri uri(String path, [Map<String, String>? query]) => origin
      .resolve('/api/public/appeals$path')
      .replace(queryParameters: query);
  static const headers = {'X-Appeal-Request': 'form'};

  Future<Json> request(
    String path, {
    String method = 'GET',
    String? token,
    Map<String, String>? query,
  }) async {
    try {
      final response = await client
          .send(
            http.Request(method, uri(path, query))
              ..headers.addAll({...headers, 'X-Capture-Token': ?token}),
          )
          .timeout(const Duration(seconds: 15));
      return decode(
        await http.Response.fromStream(
          response,
        ).timeout(const Duration(seconds: 15)),
      );
    } on AppealRequestError {
      rethrow;
    } catch (_) {
      throw AppealRequestError(
        'Не удалось связаться с сервером. Черновик сохранён — повторите попытку.',
      );
    }
  }

  Json decode(http.Response response) {
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(response.bodyBytes));
    } catch (_) {
      /* Handled below. */
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw AppealRequestError(
        body is Map && body['detail'] is String
            ? body['detail'] as String
            : response.statusCode == 413
            ? 'Фотографии слишком большие. Выберите файлы поменьше.'
            : response.statusCode == 429
            ? 'Слишком много попыток. Подождите немного; черновик сохранён.'
            : 'Сервер временно недоступен. Черновик сохранён — повторите попытку.',
        response.statusCode,
      );
    }
    if (body is! Map<String, dynamic>) {
      throw AppealRequestError(
        'Не удалось получить подтверждение сервера. Повторите попытку.',
      );
    }
    return body;
  }

  Future<Catalog> catalog() async =>
      Catalog.fromJson(await request('/catalog'));
  Future<WallPage> wall({
    required String city,
    required int page,
    required String sort,
    String organization = '',
    String search = '',
  }) async => WallPage.fromJson(
    await request(
      '/wall',
      query: {
        'city': city,
        'page': '$page',
        'sort': sort,
        if (organization.isNotEmpty) 'organization_id': organization,
        if (search.isNotEmpty) 'q': search,
      },
    ),
  );

  Future<String> submit(
    AppealForm form,
    List<LocalPhoto> photos,
    String token,
  ) async {
    final request = http.MultipartRequest('POST', uri('/submissions'))
      ..headers.addAll({...headers, 'X-Capture-Token': token})
      ..fields['metadata'] = jsonEncode({
        ...form.toJson(),
        'capture_source': 'gallery',
        'public_consent': true,
      })
      ..files.addAll(
        photos.asMap().entries.map(
          (entry) => http.MultipartFile.fromBytes(
            'photos',
            entry.value.bytes,
            filename:
                'photo-${entry.key + 1}.${entry.value.mime.contains('hei') ? 'heic' : 'jpg'}',
            contentType: MediaType.parse(entry.value.mime),
          ),
        ),
      );
    try {
      final response = await client
          .send(request)
          .timeout(const Duration(seconds: 120));
      return decode(
            await http.Response.fromStream(
              response,
            ).timeout(const Duration(seconds: 120)),
          )['number']
          as String;
    } on AppealRequestError {
      rethrow;
    } catch (_) {
      throw AppealRequestError(
        'Не удалось получить подтверждение отправки. Фотографии и текст сохранены. Нажмите «Проверить отправку».',
      );
    }
  }

  Future<String?> version() async {
    try {
      final response = await client
          .get(
            origin
                .resolve('/version.json')
                .replace(
                  queryParameters: {
                    '_': DateTime.now().millisecondsSinceEpoch.toString(),
                  },
                ),
          )
          .timeout(const Duration(seconds: 10));
      return response.statusCode == 200
          ? (jsonDecode(response.body) as Json)['version'] as String?
          : null;
    } catch (_) {
      return null;
    }
  }

  void dispose() => client.close();
}
