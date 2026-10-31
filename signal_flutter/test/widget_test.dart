import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:signal_citizens/api.dart';
import 'package:signal_citizens/app.dart';
import 'package:signal_citizens/browser_stub.dart';
import 'package:signal_citizens/controller.dart';
import 'package:signal_citizens/models.dart';
import 'package:signal_citizens/widgets/appeal_card.dart';
import 'fixtures.dart';
import 'image_client.dart';
import 'controller_test.dart' as responses;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    final font = FontLoader('Inter')
      ..addFont(rootBundle.load('assets/fonts/Inter.ttf'));
    await font.load();
    final roboto = FontLoader('Roboto')
      ..addFont(rootBundle.load('assets/fonts/Roboto.ttf'));
    await roboto.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });
  for (final width in [320.0, 390.0, 1024.0]) {
    testWidgets(
      'version update floats above the page without moving content at $width px',
      (tester) async {
        tester.view.physicalSize = Size(width, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });
        final browser = MemoryBrowser();
        final c = SignalController(
          browser: browser,
          api: SignalApi(
            origin: browser.location,
            client: MockClient(
              (request) async => responses.json(
                request.url.path.endsWith('/catalog') ? catalogJson : emptyWall,
              ),
            ),
          ),
        );
        await tester.pumpWidget(SignalApp(controller: c));
        await tester.pumpAndSettle();
        final heading = tester.getRect(find.text('Обращения жителей'));
        c.updateAvailable = true;
        c.showWall();
        await tester.pumpAndSettle();
        expect(tester.getRect(find.text('Обращения жителей')), heading);
        final notice = find.byKey(const ValueKey('version-update-notice'));
        final bounds = tester.getRect(notice);
        expect(bounds.top, greaterThan(650));
        expect(bounds.left, greaterThanOrEqualTo(16));
        expect(bounds.right, lessThanOrEqualTo(width - 16));
        expect(
          find.descendant(
            of: notice,
            matching: find.text('Доступна новая версия'),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: notice,
            matching: find.widgetWithText(FilledButton, 'Обновить'),
          ),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
      },
    );
  }
  testWidgets(
    'incomplete intake highlights fields and scrolls to the first missing item',
    (tester) async {
      tester.view.physicalSize = const Size(390, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      final requests = <String>[];
      final browser = MemoryBrowser();
      final c = SignalController(
        browser: browser,
        api: SignalApi(
          origin: browser.location,
          client: MockClient((request) async {
            requests.add(request.url.path);
            return responses.json(
              request.url.path.endsWith('/catalog') ? catalogJson : emptyWall,
            );
          }),
        ),
      );
      await tester.pumpWidget(SignalApp(controller: c));
      await tester.pumpAndSettle();
      c.newAppeal();
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Далее'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Далее'));
      await tester.pumpAndSettle();
      expect(c.step, 1);
      expect(find.text('Отметьте место проблемы на карте'), findsOneWidget);
      c.selectPoint(72.6, 61.1);
      c.nextStep();
      await tester.pumpAndSettle();
      final submit = find.widgetWithText(FilledButton, 'Отправить обращение');
      await tester.ensureVisible(submit);
      await tester.pumpAndSettle();
      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(find.text('Укажите тему обращения'), findsOneWidget);
      expect(find.text('Опишите проблему'), findsOneWidget);
      expect(
        tester.getRect(find.byKey(const ValueKey('subject'))).top,
        greaterThanOrEqualTo(0),
      );
      expect(
        tester.getRect(find.byKey(const ValueKey('subject'))).top,
        lessThan(400),
      );
      await tester.enterText(
        find.byKey(const ValueKey('subject')),
        'Не убрана площадка',
      );
      await tester.enterText(
        find.byKey(const ValueKey('description')),
        'Много листьев',
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.ensureVisible(submit);
      await tester.pumpAndSettle();
      await tester.tap(submit);
      await tester.pumpAndSettle();
      expect(find.text('Добавьте хотя бы одну фотографию'), findsOneWidget);
      expect(
        tester.getRect(find.text('Фотографии')).top,
        greaterThanOrEqualTo(0),
      );
      expect(tester.getRect(find.text('Фотографии')).top, lessThan(400));
      expect(requests.any((path) => path.endsWith('/submissions')), isFalse);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    },
  );
  for (final width in [320.0, 390.0, 480.0]) {
    testWidgets('full wall fits a $width logical pixel viewport', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
        debugNetworkImageHttpClientProvider = null;
      });
      final file = File('/private/tmp/signal-flutter-photo.jpg');
      final image =
          Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1' &&
              file.existsSync()
          ? file.readAsBytesSync()
          : base64Decode(
              'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGPsWzWdgYGBiQEMABXVAdNLhvvBAAAAAElFTkSuQmCC',
            );
      debugNetworkImageHttpClientProvider = () =>
          ImageHttpOverrides(image).createHttpClient(null);
      final browser = MemoryBrowser();
      final client = MockClient(
        (request) async => responses.json(
          request.url.path.endsWith('/catalog')
              ? catalogJson
              : {
                  'items': [
                    {
                      ...appealJson,
                      'photos': [
                        {
                          'id': 'one',
                          'url': 'http://localhost/photo',
                          'preview_url': 'http://localhost/preview',
                        },
                      ],
                      'response': {
                        'comment': 'Уборка территории запланирована на завтра.',
                        'at': '2026-10-30T07:25:00Z',
                        'photos': [],
                      },
                    },
                    {
                      ...appealJson,
                      'id': 6,
                      'number': 'ОБ-000006',
                      'subject': 'Высокая трава во дворе',
                      'status': 'IN_PROGRESS',
                      'address': '14 мкр',
                      'description':
                          'Трава закрывает бордюры и тротуар. Просим провести покос.',
                    },
                  ],
                  'total': 2,
                  'page': 1,
                  'page_size': 20,
                },
        ),
      );
      final c = SignalController(
        api: SignalApi(origin: browser.location, client: client),
        browser: browser,
      );
      final capture = GlobalKey();
      await tester.pumpWidget(
        RepaintBoundary(
          key: capture,
          child: SignalApp(controller: c),
        ),
      );
      await tester.pumpAndSettle();
      await tester.runAsync(
        () => precacheImage(
          const NetworkImage('http://localhost/preview'),
          capture.currentContext!,
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('Не убрана детская площадка'), findsOneWidget);
      final title = tester
          .getTopLeft(find.text('Не убрана детская площадка'))
          .dy;
      final status = tester.getTopLeft(find.text('Новое')).dy;
      final address = tester.getTopLeft(find.text('12 мкр')).dy;
      expect(status, lessThan(title));
      expect(title, lessThan(address));
      if (width == 390 &&
          Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1') {
        await expectLater(
          find.byKey(capture),
          matchesGoldenFile('/private/tmp/signal-flutter-wall.png'),
        );
      }
      await tester.tap(find.text('Сообщить о проблеме'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('Далее'), findsOneWidget);
      c.selectPoint(72.6, 61.1);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Далее'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Далее'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('Тема обращения'), findsOneWidget);
      expect(find.text('Описание'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
      debugNetworkImageHttpClientProvider = null;
    });
  }
  testWidgets(
    'map and compact filters select the same organization and preserve search',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      const secondId = '33333333-3333-4333-8333-333333333333';
      final original = (catalogJson['organizations'] as List).first as Map;
      final requests = <Uri>[];
      final browser = _MapBrowser();
      final c = SignalController(
        api: SignalApi(
          origin: browser.location,
          client: MockClient((request) async {
            requests.add(request.url);
            return responses.json(
              request.url.path.endsWith('/catalog')
                  ? {
                      ...catalogJson,
                      'organizations': [
                        original,
                        {...original, 'id': secondId, 'name': 'ТСЖ Соседи'},
                      ],
                    }
                  : emptyWall,
            );
          }),
        ),
        browser: browser,
      );
      await tester.pumpWidget(SignalApp(controller: c));
      await tester.pumpAndSettle();
      expect(browser.overview, isTrue);
      expect(
        find.text('Выбрать территорию второй организации'),
        findsOneWidget,
      );
      final organization = tester.getRect(
        find.byKey(const ValueKey('wall-organization-filter')),
      );
      final sorting = tester.getRect(
        find.byKey(const ValueKey('wall-sort-filter')),
      );
      expect(organization.top, sorting.top);
      expect(organization.right, lessThan(sorting.left));
      await tester.tap(find.byKey(const ValueKey('wall-sort-filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Сначала старые').last);
      await tester.pumpAndSettle();
      expect(c.sort, 'oldest');
      await tester.tap(find.text('Выбрать территорию второй организации'));
      await tester.pumpAndSettle();
      expect(c.wallOrganization, secondId);
      expect(browser.organization, secondId);
      expect(requests.last.queryParameters['organization_id'], secondId);
      await tester.tap(find.byKey(const ValueKey('map-organizations')));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'ИП Шашко'));
      await tester.pumpAndSettle();
      expect(c.wallOrganization, organizationId);
      await tester.tap(find.byKey(const ValueKey('responsibility-map-toggle')));
      await tester.pumpAndSettle();
      expect(find.text('Выбрать территорию второй организации'), findsNothing);
      expect(find.text('Сначала старые'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('responsibility-map-toggle')));
      await tester.pumpAndSettle();
      expect(browser.organization, organizationId);
      await tester.enterText(find.byType(TextField), 'листья');
      await tester.pump(const Duration(milliseconds: 350));
      await tester.pumpAndSettle();
      expect(c.search, 'листья');
      expect(c.sort, 'oldest');
      expect(c.wallOrganization, organizationId);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    },
  );
  testWidgets(
    'scrolling away and back preserves the map until it is explicitly closed',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      final browser = _ScrollMapBrowser();
      final c = SignalController(
        browser: browser,
        api: SignalApi(
          origin: browser.location,
          client: MockClient(
            (request) async => responses.json(
              request.url.path.endsWith('/catalog')
                  ? catalogJson
                  : {
                      'items': List.generate(
                        30,
                        (i) => {...appealJson, 'id': i + 1},
                      ),
                      'total': 30,
                      'page': 1,
                      'page_size': 30,
                    },
            ),
          ),
        ),
      );
      await tester.pumpWidget(SignalApp(controller: c));
      await tester.pumpAndSettle();
      expect(browser.created, 1);
      await tester.tap(find.text('Приблизить карту: 12'));
      await tester.pumpAndSettle();
      final wall = find.byKey(const PageStorageKey('wall-scroll'));
      for (var i = 0; i < 3; i++) {
        await tester.drag(wall, const Offset(0, -1800));
        await tester.pumpAndSettle();
        expect(find.text('Кто отвечает за территорию'), findsNothing);
        expect(browser.disposed, 0);
        await tester.drag(wall, const Offset(0, 2000));
        await tester.pumpAndSettle();
        expect(find.text('Приблизить карту: 13'), findsOneWidget);
        expect(browser.created, 1);
      }
      await tester.tap(find.byKey(const ValueKey('responsibility-map-toggle')));
      await tester.pumpAndSettle();
      expect(browser.disposed, 1);
      await tester.tap(find.byKey(const ValueKey('responsibility-map-toggle')));
      await tester.pumpAndSettle();
      expect(browser.created, 2);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      expect(browser.disposed, 2);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'territory picker selects 1 mkr and reaches the end of a long list',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      const names = [
        '11А мкр',
        '11Б мкр',
        '11 мкр',
        '12 мкр',
        '16 мкр',
        '1 мкр',
        '2А мкр',
        '2 мкр',
        '3 мкр',
        '4 мкр',
        '7 мкр',
        'АТБ-6',
        'Киевская',
        'Набережная',
        'ПНМК-6, ОБТОик',
        'Полигон Снежный',
        'стройдвор',
        'СУ-62',
      ];
      final owner = (catalogJson['organizations'] as List).first as Map;
      final browser = MemoryBrowser();
      final c = SignalController(
        browser: browser,
        api: SignalApi(
          origin: browser.location,
          client: MockClient(
            (request) async => responses.json(
              request.url.path.endsWith('/catalog')
                  ? {
                      ...catalogJson,
                      'organizations': [
                        {
                          ...owner,
                          'addresses': [
                            for (var i = 0; i < names.length; i++)
                              {
                                'id': 'area-$i',
                                'label': names[i],
                                'district_id': i + 1,
                              },
                          ],
                          'territories': [
                            for (var i = 0; i < names.length; i++)
                              {
                                'id': i + 1,
                                'name': names[i],
                                'geometry': polygon,
                              },
                          ],
                        },
                      ],
                    }
                  : emptyWall,
            ),
          ),
        ),
      );
      await tester.pumpWidget(SignalApp(controller: c));
      await tester.pumpAndSettle();
      c.selectAddress('area-3');
      c.selectPoint(72.6, 61.1);
      await tester.tap(find.text('Сообщить о проблеме'));
      await tester.pumpAndSettle();
      expect(find.text('Карта территории'), findsOneWidget);
      await tester.tap(find.text('12 мкр'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('choice-search')),
        '1 мкр',
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, '1 мкр'));
      await tester.pumpAndSettle();
      expect(c.form.address, '1 мкр');
      expect(c.form.addressId, 'area-5');
      expect(c.form.latitude, isNull);
      expect(c.form.longitude, isNull);
      expect(find.byType(BottomSheet), findsNothing);
      expect(find.text('Карта территории'), findsOneWidget);
      await tester.tap(find.text('1 мкр'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('СУ-62'),
        400,
        scrollable: find
            .descendant(
              of: find.byType(BottomSheet),
              matching: find.byType(Scrollable),
            )
            .last,
      );
      await tester.tap(find.widgetWithText(ListTile, 'СУ-62'));
      await tester.pumpAndSettle();
      expect(c.form.address, 'СУ-62');
      expect(c.form.addressId, 'area-17');
      await tester.tap(find.text('СУ-62'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, '11А мкр'));
      await tester.pumpAndSettle();
      expect(c.form.addressId, 'area-0');
      for (var i = 0; i < names.length; i++) {
        await tester.tap(find.text(c.form.address));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const ValueKey('choice-search')),
          names[i],
        );
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(ListTile, names[i]));
        await tester.pumpAndSettle();
        expect(c.form.addressId, 'area-$i', reason: names[i]);
        expect(c.form.address, names[i]);
        expect(find.byType(BottomSheet), findsNothing);
      }
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    },
  );
  testWidgets('photo gallery can move between photos with desktop buttons', (
    tester,
  ) async {
    debugNetworkImageHttpClientProvider = () => ImageHttpOverrides(
      base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGPsWzWdgYGBiQEMABXVAdNLhvvBAAAAAElFTkSuQmCC',
      ),
    ).createHttpClient(null);
    try {
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => TextButton(
              onPressed: () => openPhotos(context, [
                AppealPhoto.fromJson({
                  'id': 'one',
                  'url': '/one',
                  'preview_url': '/one',
                }),
                AppealPhoto.fromJson({
                  'id': 'two',
                  'url': '/two',
                  'preview_url': '/two',
                }),
              ], Uri.parse('http://localhost/')),
              child: const Text('Открыть фото'),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Открыть фото'));
      await tester.pumpAndSettle();
      expect(find.text('1 / 2'), findsOneWidget);
      await tester.tap(find.byTooltip('Следующее фото'));
      await tester.pumpAndSettle();
      expect(find.text('2 / 2'), findsOneWidget);
      await tester.tap(find.byTooltip('Закрыть фотографии'));
      await tester.pumpAndSettle();
      expect(find.text('Открыть фото'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    } finally {
      debugNetworkImageHttpClientProvider = null;
    }
  });
}

class _MapBrowser extends MemoryBrowser {
  bool overview = false;
  String organization = '';
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
  }) {
    this.overview = overview;
    organization = organizationId;
    return GestureDetector(
      onTap: () => onOrganization?.call(organizations.last.id),
      child: const ColoredBox(
        color: Color(0xffe6ede6),
        child: Center(child: Text('Выбрать территорию второй организации')),
      ),
    );
  }
}

class _ScrollMapBrowser extends MemoryBrowser {
  int created = 0, disposed = 0;
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
  }) => _MapLifetime(browser: this);
}

class _MapLifetime extends StatefulWidget {
  const _MapLifetime({required this.browser});
  final _ScrollMapBrowser browser;
  @override
  State<_MapLifetime> createState() => _MapLifetimeState();
}

class _MapLifetimeState extends State<_MapLifetime> {
  int zoom = 12;
  @override
  void initState() {
    super.initState();
    widget.browser.created++;
  }

  @override
  void dispose() {
    widget.browser.disposed++;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: const Color(0xffe6ede6),
    child: Center(
      child: TextButton(
        onPressed: () => setState(() => zoom++),
        child: Text('Приблизить карту: $zoom'),
      ),
    ),
  );
}
