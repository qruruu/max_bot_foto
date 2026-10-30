import 'dart:async';
import 'package:flutter/foundation.dart';
import 'api.dart';
import 'browser.dart';
import 'models.dart';

class SignalController extends ChangeNotifier {
  SignalController({required this.api, required this.browser})
    : form = AppealForm(city: browser.location.queryParameters['city'] ?? ''),
      online = browser.online;
  final SignalApi api;
  final SignalBrowser browser;
  Catalog? catalog;
  AppealForm form;
  List<LocalPhoto> photos = [];
  WallPage? wall;
  String? catalogError, wallError, error, receipt, token;
  String wallOrganization = '', sort = 'newest', search = '';
  int tab = 0, step = 1, page = 1, _wallRequest = 0;
  bool loading = true,
      wallLoading = false,
      busy = false,
      preparing = false,
      pending = false;
  bool restored = false, storageError = false, online, updateAvailable = false;
  bool _disposed = false;
  Timer? _draftTimer, _searchTimer, _pollTimer, _versionTimer;
  Future<void> _writes = Future.value();
  static const version = String.fromEnvironment(
    'APP_VERSION',
    defaultValue: 'development',
  );
  bool get locked => busy || preparing || pending;
  List<Organization> get organizations =>
      catalog?.organizations.where((o) => o.city == form.city).toList() ?? [];
  Organization? get recipient =>
      organizations.where((o) => o.id == form.organizationId).firstOrNull;
  Json? get address =>
      recipient?.addresses.where((a) => a['id'] == form.addressId).firstOrNull;

  Future<void> initialize() async {
    await Future.wait([
      browser
          .loadDraft()
          .then((draft) {
            if (draft == null) return;
            if (draft.receipt != null) {
              receipt = draft.receipt;
              return;
            }
            if (!draft.hasContent) return;
            form = draft.form;
            photos = draft.photos;
            token = draft.token;
            pending = draft.pending;
            restored = true;
            tab = 1;
            step = 2;
          })
          .catchError((_) {
            storageError = true;
          }),
      api
          .catalog()
          .then((result) {
            catalog = result;
          })
          .catchError((Object failure) {
            catalogError = failure.toString();
          }),
    ]);
    if (_disposed) return;
    if (!pending) _reconcile();
    _syncWallOrganization();
    loading = false;
    browser.listen(
      connectivity: (value) {
        online = value;
        _notify();
        if (value) unawaited(refreshWall());
      },
      activity: () {
        if (tab == 0) unawaited(refreshWall());
      },
    );
    _pollTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (online && tab == 0) unawaited(refreshWall());
    });
    if (version != 'development') {
      _versionTimer = Timer.periodic(const Duration(seconds: 45), (_) async {
        final latest = await api.version();
        if (latest != null && latest != version) {
          updateAvailable = true;
          _notify();
        }
      });
    }
    _dirty();
    _notify();
    await refreshWall();
  }

  void _reconcile() {
    final cities = catalog?.cities ?? [];
    if (!cities.contains(form.city)) {
      form.city = cities.length == 1 ? cities.first : '';
    }
    final options = organizations;
    if (!options.any((o) => o.id == form.organizationId)) {
      form.organizationId = options.length == 1 ? options.first.id : '';
      form.addressId = '';
      form.address = '';
      form.latitude = null;
      form.longitude = null;
    }
    final addresses = recipient?.addresses ?? [];
    if (!addresses.any((a) => a['id'] == form.addressId)) {
      final selected = addresses.length == 1 ? addresses.first : null;
      form.addressId = selected?['id'] as String? ?? '';
      form.address = selected?['label'] as String? ?? '';
      form.latitude = null;
      form.longitude = null;
    }
  }

  void _syncWallOrganization() {
    if (organizations.length == 1) {
      wallOrganization = organizations.first.id;
    } else if (!organizations.any((o) => o.id == wallOrganization)) {
      wallOrganization = '';
    }
  }

  Future<void> retryCatalog() async {
    catalogError = null;
    _notify();
    try {
      catalog = await api.catalog();
      if (!pending) _reconcile();
      _syncWallOrganization();
    } catch (failure) {
      catalogError = failure.toString();
    }
    _notify();
  }

  void selectCity(String value) {
    if (locked) return;
    form.city = value;
    form.organizationId = '';
    _reconcile();
    _syncWallOrganization();
    page = 1;
    step = 1;
    wall = null;
    _changed();
    unawaited(refreshWall());
  }

  void selectOrganization(String value) {
    if (locked) return;
    form.organizationId = value;
    form.addressId = '';
    _reconcile();
    _changed();
  }

  void selectAddress(String value) {
    if (locked) return;
    final selected = recipient?.addresses
        .where((a) => a['id'] == value)
        .firstOrNull;
    form.addressId = selected?['id'] as String? ?? '';
    form.address = selected?['label'] as String? ?? '';
    form.latitude = null;
    form.longitude = null;
    _changed();
  }

  void selectPoint(double longitude, double latitude) {
    if (locked || address == null) return;
    final district = recipient?.territories
        .where((t) => t['id'] == address!['district_id'])
        .firstOrNull;
    if (district == null ||
        !coversPoint(
          Json.from(district['geometry'] as Map),
          longitude,
          latitude,
        )) {
      error = 'Выберите место внутри выделенной территории организации.';
      _notify();
      return;
    }
    form.longitude = longitude;
    form.latitude = latitude;
    error = null;
    _changed();
  }

  void changeText({
    String? subject,
    String? description,
    String? place,
    String? contact,
  }) {
    if (locked) return;
    if (subject != null) form.subject = subject;
    if (description != null) form.description = description;
    if (place != null) form.place = place;
    if (contact != null) form.contact = contact;
    _changed();
  }

  void showWall() {
    tab = 0;
    _notify();
    unawaited(refreshWall());
  }

  void dismissReceipt() {
    receipt = null;
    unawaited(_persist());
    _notify();
  }

  void newAppeal() {
    if (locked) return;
    receipt = null;
    tab = 1;
    step = 1;
    error = null;
    _reconcile();
    _changed();
  }

  void nextStep() {
    if (form.located && !locked) {
      step = 2;
      error = null;
      _notify();
    }
  }

  void backStep() {
    if (!locked) {
      step = 1;
      error = null;
      _notify();
    }
  }

  Future<void> refreshWall() async {
    if (form.city.isEmpty || _disposed) return;
    final request = ++_wallRequest;
    wallLoading = true;
    _notify();
    try {
      final result = await api.wall(
        city: form.city,
        page: page,
        sort: sort,
        organization: wallOrganization,
        search: search,
      );
      if (_disposed || request != _wallRequest) return;
      if (page > result.pages) {
        page = result.pages;
        unawaited(refreshWall());
        return;
      }
      wall = result;
      wallError = null;
    } catch (failure) {
      if (request == _wallRequest) wallError = failure.toString();
    } finally {
      if (request == _wallRequest) {
        wallLoading = false;
        _notify();
      }
    }
  }

  void filterWall({String? organization, String? order, int? pageNumber}) {
    if (organization != null) wallOrganization = organization;
    if (order != null) sort = order;
    page = pageNumber ?? 1;
    _notify();
    unawaited(refreshWall());
  }

  void searchWall(String value, {bool immediate = false}) {
    _searchTimer?.cancel();
    void apply() {
      search = value.trim();
      page = 1;
      unawaited(refreshWall());
    }

    if (immediate) {
      apply();
    } else {
      _searchTimer = Timer(const Duration(milliseconds: 300), apply);
    }
  }

  Future<void> addPhotos() async {
    if (locked) return;
    preparing = true;
    error = null;
    _notify();
    try {
      final added = await browser.pickPhotos(3 - photos.length);
      if (added.length + photos.length > 3) {
        throw AppealRequestError('Можно приложить до трёх фотографий');
      }
      photos = [...photos, ...added];
      await _persist();
    } catch (failure) {
      error = failure.toString().replaceFirst('Error: ', '');
    } finally {
      preparing = false;
      _dirty();
      _notify();
    }
  }

  void beginPhotoDrop() {
    if (locked || _disposed) return;
    preparing = true;
    error = null;
    _notify();
  }

  Future<void> finishPhotoDrop(List<LocalPhoto> added) async {
    if (_disposed) return;
    try {
      if (added.length + photos.length > 3) {
        throw AppealRequestError('Можно приложить до трёх фотографий');
      }
      photos = [...photos, ...added];
      await _persist();
    } catch (failure) {
      error = failure.toString();
    } finally {
      preparing = false;
      _dirty();
      _notify();
    }
  }

  void failPhotoDrop(String message) {
    if (_disposed) return;
    error = message;
    preparing = false;
    _dirty();
    _notify();
  }

  void removePhoto(String id) {
    if (!locked) {
      photos = photos.where((p) => p.id != id).toList();
      _changed();
    }
  }

  Future<void> submit() async {
    if (busy || preparing) return;
    if (!pending &&
        (!form.located ||
            recipient == null ||
            photos.isEmpty ||
            form.subject.trim().isEmpty ||
            form.description.trim().isEmpty)) {
      error =
          'Укажите тему и описание, выберите место на карте и приложите фото.';
      _notify();
      return;
    }
    busy = true;
    error = null;
    _notify();
    var attempted = pending;
    try {
      if (token != null) {
        try {
          final resumed = await api.request(
            '/capture-sessions/resume',
            method: 'POST',
            token: token,
          );
          if (resumed['submitted'] != null) {
            await _complete((resumed['submitted'] as Json)['number'] as String);
            return;
          }
          if (resumed['expired'] == true) token = null;
        } on AppealRequestError catch (failure) {
          if (failure.status == 409) {
            token = null;
          } else {
            rethrow;
          }
        }
      }
      token ??=
          (await api.request('/sessions', method: 'POST'))['token'] as String;
      pending = true;
      await _persist(required: true);
      attempted = true;
      await _complete(await api.submit(form, photos, token!));
    } catch (failure) {
      if (failure is AppealRequestError && !failure.uncertain) {
        pending = false;
      } else {
        pending = attempted;
      }
      if (failure is AppealRequestError && failure.status == 422) {
        step = 1;
        unawaited(retryCatalog());
      }
      error = failure.toString();
      unawaited(_persist());
    } finally {
      busy = false;
      _dirty();
      _notify();
    }
  }

  Future<void> _complete(String number) async {
    receipt = number;
    pending = false;
    token = null;
    photos = [];
    form = AppealForm(city: form.city);
    _reconcile();
    tab = 0;
    step = 1;
    restored = false;
    error = null;
    await _persist();
    unawaited(refreshWall());
  }

  AppealDraft _snapshot() => AppealDraft(
    form: AppealForm.fromJson(form.toJson()),
    photos: List.of(photos),
    token: token,
    pending: pending,
    receipt: receipt,
  );
  Future<void> _persist({bool required = false}) {
    _draftTimer?.cancel();
    final snapshot = _snapshot();
    final operation = _writes.then((_) => browser.saveDraft(snapshot));
    _writes = operation.catchError((_) {
      storageError = true;
      _notify();
    });
    return required ? operation : _writes;
  }

  void _changed() {
    _dirty();
    _draftTimer?.cancel();
    _draftTimer = Timer(
      const Duration(milliseconds: 350),
      () => unawaited(_persist()),
    );
    _notify();
  }

  void _dirty() => browser.setDirty(
    receipt == null && (form.hasText || photos.isNotEmpty || pending),
  );
  Future<void> applyUpdate() async {
    if (busy || preparing) return;
    try {
      await _persist(required: true);
      browser.reload();
    } catch (_) {
      error = 'Не удалось сохранить черновик. Не закрывайте страницу.';
      _notify();
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _draftTimer?.cancel();
    _searchTimer?.cancel();
    _pollTimer?.cancel();
    _versionTimer?.cancel();
    browser.dispose();
    api.dispose();
    super.dispose();
  }
}
