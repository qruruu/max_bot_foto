import 'dart:convert';
import 'dart:js_interop';
import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;
import 'browser.dart';
import 'models.dart';
import 'theme.dart';

@JS('signalBrowser.loadDraft')
external JSPromise<JSString?> _loadDraft();
@JS('signalBrowser.saveDraft')
external JSPromise<JSAny?> _saveDraft(JSString json);
@JS('signalBrowser.pickPhotos')
external JSPromise<JSString> _pickPhotos(JSNumber remaining);
@JS('signalBrowser.setDirty')
external void _setDirty(JSBoolean value);
@JS('signalBrowser.listen')
external JSString _listen(JSFunction connectivity, JSFunction activity);
@JS('signalBrowser.unlisten')
external void _unlisten(JSString id);
@JS('signalBrowser.createMap')
external JSPromise<JSString> _createMap(
  JSAny element,
  JSString configuration,
  JSFunction point,
  JSFunction organization,
);
@JS('signalBrowser.cancelMap')
external void _cancelMap(JSAny element);
@JS('signalBrowser.destroyMap')
external void _destroyMap(JSString id);
@JS('signalBrowser.setMapPoint')
external void _setMapPoint(JSString id, JSNumber longitude, JSNumber latitude);

@JS('signalBrowser.registerDropTarget')
external JSString _registerDropTarget(
  JSFunction bounds,
  JSFunction started,
  JSFunction photos,
  JSFunction error,
);
@JS('signalBrowser.unregisterDropTarget')
external void _unregisterDropTarget(JSString id);

SignalBrowser createBrowser() => WebSignalBrowser();

class WebSignalBrowser implements SignalBrowser {
  String? _listener;
  @override
  Uri get location => Uri.parse(web.window.location.href);
  @override
  bool get online => web.window.navigator.onLine;
  @override
  Future<AppealDraft?> loadDraft() async {
    final result = await _loadDraft().toDart;
    return result == null
        ? null
        : AppealDraft.fromJson(jsonDecode(result.toDart) as Json);
  }

  @override
  Future<void> saveDraft(AppealDraft draft) async {
    await _saveDraft(jsonEncode(draft.toJson()).toJS).toDart;
  }

  @override
  Future<List<LocalPhoto>> pickPhotos(int remaining) async =>
      (jsonDecode((await _pickPhotos(remaining.toJS).toDart).toDart) as List)
          .map((item) => LocalPhoto.fromJson(Json.from(item as Map)))
          .toList();
  @override
  Future<void> copy(String value) async {
    await web.window.navigator.clipboard.writeText(value).toDart;
  }

  @override
  void setDirty(bool value) => _setDirty(value.toJS);
  @override
  void reload() {
    _setDirty(false.toJS);
    web.window.location.reload();
  }

  @override
  void listen({
    required void Function(bool) connectivity,
    required VoidCallback activity,
  }) {
    _listener = _listen(
      ((JSBoolean value) => connectivity(value.toDart)).toJS,
      activity.toJS,
    ).toDart;
  }

  @override
  Widget map({
    required String apiKey,
    required List<Organization> organizations,
    String organizationId = '',
    bool overview = false,
    bool preview = false,
    int? districtId,
    double? longitude,
    double? latitude,
    void Function(double longitude, double latitude)? onPoint,
    ValueChanged<String>? onOrganization,
  }) => YandexMap(
    key: ValueKey('$organizationId:$districtId'),
    configuration: {
      'apiKey': apiKey,
      'organizations': organizations.map((item) => item.json).toList(),
      'organizationId': organizationId,
      'overview': overview,
      'preview': preview,
      'districtId': districtId,
      'point': longitude == null ? null : [longitude, latitude],
      'picking': onPoint != null,
    },
    onPoint: onPoint,
    onOrganization: onOrganization,
  );
  @override
  Widget photoDropTarget({
    required Widget child,
    required int remaining,
    required bool enabled,
    required VoidCallback onStart,
    required Future<void> Function(List<LocalPhoto>) onPhotos,
    required ValueChanged<String> onError,
  }) => _PhotoDropTarget(
    remaining: remaining,
    enabled: enabled,
    onStart: onStart,
    onPhotos: onPhotos,
    onError: onError,
    child: child,
  );
  @override
  void dispose() {
    if (_listener != null) _unlisten(_listener!.toJS);
  }
}

class YandexMap extends StatefulWidget {
  const YandexMap({
    super.key,
    required this.configuration,
    this.onPoint,
    this.onOrganization,
  });
  final Json configuration;
  final void Function(double, double)? onPoint;
  final ValueChanged<String>? onOrganization;
  @override
  State<YandexMap> createState() => _YandexMapState();
}

class _YandexMapState extends State<YandexMap> {
  String? _handle, _error;
  web.HTMLDivElement? _element;
  bool _ready = false;
  int _attempt = 0;
  Future<void> _create(web.HTMLDivElement element) async {
    _element = element;
    final attempt = _attempt;
    bool current() =>
        mounted && _attempt == attempt && identical(_element, element);
    try {
      final id = (await _createMap(
        element,
        jsonEncode(widget.configuration).toJS,
        ((JSNumber lon, JSNumber lat) {
          if (current()) {
            widget.onPoint?.call(lon.toDartDouble, lat.toDartDouble);
          }
        }).toJS,
        ((JSString id) {
          if (current()) widget.onOrganization?.call(id.toDart);
        }).toJS,
      ).toDart).toDart;
      if (!current()) {
        _destroyMap(id.toJS);
        return;
      }
      _handle = id;
      setState(() => _ready = true);
    } catch (_) {
      if (current()) {
        setState(
          () => _error = 'Не удалось открыть карту. Попробуйте ещё раз.',
        );
      }
    }
  }

  @override
  void didUpdateWidget(YandexMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    final point = widget.configuration['point'] as List?;
    if (_handle != null && point != null) {
      _setMapPoint(
        _handle!.toJS,
        (point[0] as num).toDouble().toJS,
        (point[1] as num).toDouble().toJS,
      );
    }
  }

  void _release() {
    final element = _element;
    _element = null;
    if (element != null) _cancelMap(element);
    if (_handle != null) _destroyMap(_handle!.toJS);
    _handle = null;
  }

  @override
  void dispose() {
    _release();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(12),
    child: Stack(
      children: [
        if (_error == null)
          Positioned.fill(
            child: HtmlElementView.fromTagName(
              key: ValueKey(_attempt),
              tagName: 'div',
              onElementCreated: (element) {
                final div = element as web.HTMLDivElement;
                div.style.width = '100%';
                div.style.height = '100%';
                _create(div);
              },
            ),
          ),
        if (!_ready && _error == null)
          const Positioned.fill(
            child: IgnorePointer(
              child: ColoredBox(
                color: surface,
                child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            ),
          ),
        if (_error != null)
          Positioned.fill(
            child: ColoredBox(
              color: paleGreen,
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(_error!, textAlign: TextAlign.center),
                    const SizedBox(height: 10),
                    TextButton.icon(
                      onPressed: () => setState(() {
                        _release();
                        _error = null;
                        _ready = false;
                        _attempt++;
                      }),
                      icon: const Icon(Icons.refresh),
                      label: const Text('Попробовать снова'),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    ),
  );
}

class _PhotoDropTarget extends StatefulWidget {
  const _PhotoDropTarget({
    required this.child,
    required this.remaining,
    required this.enabled,
    required this.onStart,
    required this.onPhotos,
    required this.onError,
  });
  final Widget child;
  final int remaining;
  final bool enabled;
  final VoidCallback onStart;
  final Future<void> Function(List<LocalPhoto>) onPhotos;
  final ValueChanged<String> onError;
  @override
  State<_PhotoDropTarget> createState() => _PhotoDropTargetState();
}

class _PhotoDropTargetState extends State<_PhotoDropTarget> {
  final region = GlobalKey();
  String? id;
  @override
  void initState() {
    super.initState();
    id = _registerDropTarget(
      (() {
        final box = region.currentContext?.findRenderObject();
        if (!mounted ||
            !widget.enabled ||
            box is! RenderBox ||
            !box.attached ||
            !box.hasSize) {
          return 'null'.toJS;
        }
        final offset = box.localToGlobal(Offset.zero);
        return jsonEncode({
          'left': offset.dx,
          'top': offset.dy,
          'right': offset.dx + box.size.width,
          'bottom': offset.dy + box.size.height,
          'remaining': widget.remaining,
        }).toJS;
      }).toJS,
      (() => widget.onStart()).toJS,
      ((JSString value) {
        // Completion still belongs to the controller if the window changes layout.
        return (() async {
          await widget.onPhotos(
            (jsonDecode(value.toDart) as List)
                .map((item) => LocalPhoto.fromJson(Json.from(item as Map)))
                .toList(),
          );
          return null;
        })().toJS;
      }).toJS,
      ((JSString error) => widget.onError(error.toDart)).toJS,
    ).toDart;
  }

  @override
  void dispose() {
    if (id != null) _unregisterDropTarget(id!.toJS);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      SizedBox(key: region, child: widget.child);
}
