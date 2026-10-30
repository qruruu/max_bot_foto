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
import 'package:signal_citizens/widgets/desktop_appeal_card.dart';
import 'fixtures.dart';
import 'image_client.dart';
import 'controller_test.dart' as responses;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    for (final (family, asset) in [
      ('Inter', 'assets/fonts/Inter.ttf'),
      ('Roboto', 'assets/fonts/Roboto.ttf'),
      ('MaterialIcons', 'fonts/MaterialIcons-Regular.otf'),
    ]) {
      await (FontLoader(family)..addFont(rootBundle.load(asset))).load();
    }
  });
  for (final width in [960.0, 1024.0, 1440.0]) {
    testWidgets(
      'desktop wall and both form steps fit $width px and retain the mobile draft',
      (tester) async {
        tester.view.physicalSize = Size(width, 650);
        tester.view.devicePixelRatio = 1;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
          debugNetworkImageHttpClientProvider = null;
        });
        final file = File('/private/tmp/signal-flutter-photo.jpg');
        final bytes =
            Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1' &&
                file.existsSync()
            ? file.readAsBytesSync()
            : base64Decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGPsWzWdgYGBiQEMABXVAdNLhvvBAAAAAElFTkSuQmCC',
              );
        debugNetworkImageHttpClientProvider = () =>
            ImageHttpOverrides(bytes).createHttpClient(null);
        final browser = MemoryBrowser()
          ..draft = AppealDraft(
            form: AppealForm(city: 'Нефтеюганск'),
            photos: [],
            receipt: 'ОБ-000009',
          );
        final original = (catalogJson['organizations'] as List).first as Map;
        final catalog = {
          ...catalogJson,
          'organizations': [
            {
              ...original,
              'addresses': [
                ...(original['addresses'] as List),
                {'id': 'second-area', 'label': '11Б мкр', 'district_id': 2},
              ],
              'territories': [
                ...(original['territories'] as List),
                {'id': 2, 'name': '11Б мкр', 'geometry': polygon},
              ],
            },
          ],
        };
        final c = SignalController(
          browser: browser,
          api: SignalApi(
            origin: browser.location,
            client: MockClient(
              (request) async => responses.json(
                request.url.path.endsWith('/catalog')
                    ? catalog
                    : {
                        'items': [
                          {
                            ...appealJson,
                            'subject': 'Не убрана площадка',
                            'description':
                                'На детской площадке не убран мусор. Просьба привести территорию в порядок и проверить состояние оборудования.',
                            'photos': [
                              {
                                'id': 'one',
                                'url': '/photo',
                                'preview_url': '/preview',
                              },
                            ],
                            'response': {
                              'comment':
                                  'Здравствуйте! Территория убрана. Спасибо за обращение.',
                              'at': '2026-11-01T04:25:00Z',
                              'photos': [],
                            },
                          },
                          {
                            ...appealJson,
                            'id': 6,
                            'number': 'ОБ-000006',
                            'subject': 'Высокая трава во дворе',
                            'status': 'IN_PROGRESS',
                            'address': '11Б мкр',
                            'description':
                                'Трава закрывает бордюры и тротуар. Просим провести покос.',
                            'photos': [
                              {
                                'id': 'two',
                                'url': '/photo',
                                'preview_url': '/preview',
                              },
                            ],
                          },
                        ],
                        'total': 2,
                        'page': 1,
                        'page_size': 20,
                      },
              ),
            ),
          ),
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
        expect(
          tester.widget<Scaffold>(find.byType(Scaffold)).bottomNavigationBar,
          isNull,
        );
        final first = tester.getRect(find.byType(DesktopAppealCard).first);
        final second = tester.getRect(find.byType(DesktopAppealCard).last);
        expect(first.top, second.top);
        expect(first.right, lessThan(second.left));
        expect(
          tester.getTopLeft(find.byKey(const ValueKey('wall-sort-filter'))).dy,
          tester.getTopLeft(find.byType(TextField)).dy,
        );
        if (width == 1024 &&
            Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1') {
          await expectLater(
            find.byKey(capture),
            matchesGoldenFile('/private/tmp/signal-desktop-wall.png'),
          );
        }
        await tester.tap(find.byTooltip('Скрыть уведомление'));
        await tester.pumpAndSettle();
        expect(c.receipt, isNull);
        await tester.tap(find.byKey(const ValueKey('desktop-map-toggle')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await tester.tap(find.byKey(const ValueKey('desktop-map-toggle')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Сообщить о проблеме'));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('desktop-place-columns')),
          findsOneWidget,
        );
        expect(
          find.text('Выберите территорию,\nчтобы открыть карту'),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        if (width == 1024 &&
            Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1') {
          await expectLater(
            find.byKey(capture),
            matchesGoldenFile('/private/tmp/signal-desktop-place.png'),
          );
        }
        await tester.tap(find.text('Выберите территорию'));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(ListTile, '12 мкр'));
        await tester.pumpAndSettle();
        c.selectPoint(72.6, 61.1);
        await tester.pumpAndSettle();
        await tester.tap(find.text('Далее'));
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('desktop-description-columns')),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        if (width == 1024 &&
            Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1') {
          await expectLater(
            find.byKey(capture),
            matchesGoldenFile('/private/tmp/signal-desktop-description.png'),
          );
        }
        await tester.enterText(
          find.byKey(const ValueKey('subject')),
          'Моя жалоба на площадку',
        );
        await tester.enterText(
          find.byKey(const ValueKey('description')),
          'Нужно убрать мусор на площадке.',
        );
        await tester.pump(const Duration(milliseconds: 400));
        c.beginPhotoDrop();
        await c.finishPhotoDrop([
          LocalPhoto(
            id: 'desktop-drop',
            name: 'photo.jpg',
            mime: 'image/jpeg',
            bytes: bytes,
            preview: bytes,
          ),
        ]);
        await tester.pumpAndSettle();
        expect(c.photos.length, 1);
        expect(tester.takeException(), isNull);
        tester.view.physicalSize = const Size(390, 844);
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('desktop-description-columns')),
          findsNothing,
        );
        expect(c.form.subject, 'Моя жалоба на площадку');
        expect(
          tester
              .widget<TextFormField>(find.byKey(const ValueKey('subject')))
              .initialValue,
          c.form.subject,
        );
        expect(tester.takeException(), isNull);
        tester.view.physicalSize = Size(width, 650);
        await tester.pumpAndSettle();
        expect(
          find.byKey(const ValueKey('desktop-description-columns')),
          findsOneWidget,
        );
        expect(
          tester
              .widget<TextFormField>(find.byKey(const ValueKey('description')))
              .initialValue,
          c.form.description,
        );
        expect(c.form.located, isTrue);
        expect(c.photos.single.id, 'desktop-drop');
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
        debugNetworkImageHttpClientProvider = null;
      },
    );
  }
}
