import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:signal_citizens/browser_stub.dart';
import 'package:signal_citizens/models.dart';
import 'package:signal_citizens/theme.dart';
import 'package:signal_citizens/widgets/appeal_card.dart';
import 'fixtures.dart';
import 'image_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    for (final (family, asset) in [
      ('Roboto', 'assets/fonts/Roboto.ttf'),
      ('MaterialIcons', 'fonts/MaterialIcons-Regular.otf'),
    ]) {
      await (FontLoader(family)..addFont(rootBundle.load(asset))).load();
    }
  });

  testWidgets(
    'reference card expands the complaint and keeps its gallery and link',
    (tester) async {
      tester.view.physicalSize = const Size(524, 720);
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      final preview = Platform.environment['SIGNAL_PREVIEW_PHOTO'];
      final bytes = preview == null
          ? base64Decode(
              'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGPsWzWdgYGBiQEMABXVAdNLhvvBAAAAAElFTkSuQmCC',
            )
          : File(preview).readAsBytesSync();
      debugNetworkImageHttpClientProvider = () =>
          ImageHttpOverrides(bytes).createHttpClient(null);
      final browser = MemoryBrowser();
      final capture = GlobalKey();
      const description =
          'На площадке много листьев, мусор лежит уже несколько дней. '
          'Дети играют рядом с разбросанными отходами. '
          'Просим провести уборку и проверить состояние площадки.';
      try {
        await tester.pumpWidget(
          MaterialApp(
            theme: signalTheme(),
            home: Scaffold(
              backgroundColor: const Color(0xfffbf8f4),
              body: SingleChildScrollView(
                child: RepaintBoundary(
                  key: capture,
                  child: ColoredBox(
                    color: const Color(0xfffbf8f4),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(8, 9, 4, 14),
                      child: AppealCard(
                        browser: browser,
                        origin: Uri.parse('http://localhost/'),
                        appeal: Appeal.fromJson({
                          ...appealJson,
                          'description': description,
                          'photos': [
                            {
                              'id': 'reference',
                              'url': '/reference',
                              'preview_url': '/reference',
                            },
                          ],
                          'response': {
                            'comment': 'Уборка запланирована на завтра.',
                            'at': '2026-10-30T07:25:00Z',
                            'photos': [],
                          },
                        }),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.runAsync(
          () => precacheImage(
            const NetworkImage('http://localhost/reference'),
            capture.currentContext!,
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.text('ОБ-000007 · 30.10.2026'), findsOneWidget);
        expect(find.text('Читать полностью'), findsOneWidget);
        expect(find.byIcon(Icons.content_copy_outlined), findsNothing);
        expect(find.text('1 фото'), findsNothing);
        if (Platform.environment['SIGNAL_WRITE_PREVIEWS'] == '1') {
          await expectLater(
            find.byKey(capture),
            matchesGoldenFile('/private/tmp/signal-flutter-card.png'),
          );
        }
        await tester.tap(find.text('Читать полностью'));
        await tester.pumpAndSettle();
        expect(tester.widget<Text>(find.text(description)).maxLines, isNull);
        await tester.tap(find.text('Свернуть'));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<Text>(find.textContaining('На площадке много листьев'))
              .maxLines,
          3,
        );
        await tester.longPress(find.text('Не убрана детская площадка'));
        await tester.pumpAndSettle();
        expect(browser.copied, 'http://localhost/a/7');
        await tester.tap(find.byType(PhotoThumbnail));
        await tester.pumpAndSettle();
        expect(find.text('1 / 1'), findsOneWidget);
        await tester.tap(find.byTooltip('Закрыть фотографии'));
        await tester.pumpAndSettle();
        expect(find.text('Не убрана детская площадка'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
      } finally {
        debugNetworkImageHttpClientProvider = null;
      }
    },
  );
  testWidgets('an unbroken complaint keeps a readable preview', (tester) async {
    final text = 'Ж' * 500;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 240,
            child: AppealDescription(
              text: text,
              scale: 1,
              expanded: false,
              onToggle: () {},
            ),
          ),
        ),
      ),
    );
    final preview = tester.widget<Text>(find.textContaining('Ж')).data!;
    expect(preview.length, greaterThan(30));
    expect(preview, endsWith('…'));
    expect(find.text('Читать полностью'), findsOneWidget);
  });
  testWidgets('old appeals without a subject do not repeat their complaint', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: signalTheme(),
        home: Scaffold(
          body: SizedBox(
            width: 358,
            child: AppealCard(
              browser: MemoryBrowser(),
              origin: Uri.parse('http://localhost/'),
              appeal: Appeal.fromJson({
                ...appealJson,
                'subject': '',
                'description': 'много листьев',
              }),
            ),
          ),
        ),
      ),
    );
    expect(find.text('много листьев'), findsOneWidget);
    expect(find.text('12 мкр'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
