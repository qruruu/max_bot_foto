import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:signal_citizens/api.dart';
import 'package:signal_citizens/app.dart';
import 'package:signal_citizens/controller.dart';
import 'fixtures.dart';
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
  for (final width in [320.0, 390.0, 1440.0]) {
    testWidgets('full application confirms and revisits a place at $width px', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      final owner = (catalogJson['organizations'] as List).first as Map;
      final browser = PickingBrowser()..mapReady = false;
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
                            ...(owner['addresses'] as List),
                            {
                              'id': 'second',
                              'label': 'Другая территория',
                              'district_id': 2,
                            },
                          ],
                          'territories': [
                            ...(owner['territories'] as List),
                            {
                              'id': 2,
                              'name': 'Другая территория',
                              'geometry': {
                                'type': 'Polygon',
                                'coordinates': [
                                  [
                                    [74, 61],
                                    [75, 61],
                                    [75, 62],
                                    [74, 62],
                                    [74, 61],
                                  ],
                                ],
                              },
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
      await tester.tap(find.text('Сообщить о проблеме'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Выбрать место на карте'));
      await tester.tap(find.text('Выбрать место на карте'));
      await tester.pumpAndSettle();
      expect(find.text('Выберите территорию'), findsNWidgets(2));
      await tester.tap(find.text('Выберите территорию').first);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, '12 мкр'));
      await tester.pumpAndSettle();

      final screen = find.byKey(const ValueKey('place-picker-screen'));
      expect(tester.getSize(screen), Size(width, 844));
      expect(find.text('Сигнал'), findsNothing);
      expect(find.text('Стена города'), findsNothing);
      expect(find.text('НОВОЕ ОБРАЩЕНИЕ'), findsNothing);
      final confirm = find.widgetWithText(FilledButton, 'Подтвердить место');
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);

      // Loading and invalid points cannot enable confirmation.
      browser.pickPoint!(70, 61);
      await tester.pumpAndSettle();
      expect(
        find.text('Выберите место внутри выделенной территории организации.'),
        findsOneWidget,
      );
      browser.pickPoint!(72.75, 61.75); // Hole in the territory.
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      browser.pickPoint!(72.6, 61.1);
      await tester.pumpAndSettle();
      expect(c.form.located, isFalse);
      expect(c.step, 1);
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      browser.mapReady = true;
      browser.readyChanged!(true);
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(confirm).onPressed, isNotNull);

      // A map touch is provisional, including when the route is closed.
      await tester.tap(find.byTooltip('Назад к территории'));
      await tester.pumpAndSettle();
      expect(c.step, 1);
      expect(c.form.located, isFalse);
      await tester.tap(find.text('Выбрать место на карте'));
      await tester.pumpAndSettle();
      expect(browser.shownLongitude, isNull);
      await tester.tap(find.byKey(const ValueKey('test-picking-map')));
      await tester.pumpAndSettle();
      browser.pickPoint!(72.65, 61.15);
      await tester.pumpAndSettle();
      expect(browser.shownLongitude, 72.65);
      expect(c.step, 1);
      await tester.tap(confirm);
      await tester.pumpAndSettle();
      expect(c.step, 2);
      expect(c.form.longitude, 72.65);
      await tester.enterText(
        find.byKey(const ValueKey('subject')),
        'Сломана скамейка',
      );
      await tester.enterText(
        find.byKey(const ValueKey('description')),
        'Нужно починить скамейку во дворе',
      );
      c.photos.add(photo());
      c.changeText(place: 'У подъезда', contact: 'test@example.test');
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('12 мкр'));
      await tester.tap(find.text('12 мкр'));
      await tester.pumpAndSettle();
      expect(browser.shownLongitude, 72.65);
      expect(browser.shownLatitude, 61.15);
      tester.view.physicalSize = const Size(844, 390);
      await tester.pumpAndSettle();
      expect(tester.getSize(screen), const Size(844, 390));
      expect(browser.shownLongitude, 72.65);
      expect(tester.takeException(), isNull);
      tester.view.physicalSize = Size(width, 844);
      await tester.pumpAndSettle();

      // Reopening and changing a point preserves the rest of the draft.
      browser.pickPoint!(72.66, 61.16);
      await tester.pumpAndSettle();
      await tester.tap(confirm);
      await tester.pumpAndSettle();
      expect(c.form.subject, 'Сломана скамейка');
      expect(c.form.description, 'Нужно починить скамейку во дворе');
      expect(c.form.place, 'У подъезда');
      expect(c.form.contact, 'test@example.test');
      expect(c.photos.single.id, 'photo-1');
      expect(c.form.longitude, 72.66);
      await tester.tap(find.text('12 мкр'));
      await tester.pumpAndSettle();
      browser.pickPoint!(72.67, 61.17);
      await tester.pumpAndSettle();
      // The system/browser back follows the same cancellation path.
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(c.step, 1);
      expect(c.form.longitude, 72.66);
      await tester.tap(find.text('12 мкр'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'Другая территория'));
      await tester.pumpAndSettle();
      expect(c.form.addressId, 'second');
      expect(c.form.located, isFalse);
      expect(browser.shownLongitude, isNull);
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      browser.pickPoint!(72.66, 61.16);
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      browser.pickPoint!(74.5, 61.5);
      await tester.pumpAndSettle();
      await tester.tap(confirm);
      await tester.pumpAndSettle();
      expect(c.step, 2);
      expect(c.form.longitude, 74.5);
      expect(c.form.subject, 'Сломана скамейка');
      expect(c.photos.single.id, 'photo-1');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    });
  }
}
