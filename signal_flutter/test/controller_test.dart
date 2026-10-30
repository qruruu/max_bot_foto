import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:signal_citizens/api.dart';
import 'package:signal_citizens/browser_stub.dart';
import 'package:signal_citizens/controller.dart';
import 'package:signal_citizens/models.dart';
import 'fixtures.dart';

http.Response json(Object value, [int status = 200]) => http.Response(
  jsonEncode(value),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

void main() {
  test(
    'version update saves the draft before reload and allows retry after storage failure',
    () async {
      final browser = _UpdateBrowser();
      final c = SignalController(
        browser: browser,
        api: SignalApi(
          origin: browser.location,
          client: MockClient(
            (request) async => json(
              request.url.path.endsWith('/catalog') ? catalogJson : emptyWall,
            ),
          ),
        ),
      );
      await c.initialize();
      c.changeText(subject: 'Сохранить перед обновлением');
      browser.failSave = true;
      await c.applyUpdate();
      expect(browser.reloads, 0);
      expect(c.updating, isFalse);
      expect(c.updateError, contains('Не удалось сохранить черновик'));
      browser.failSave = false;
      browser.pendingSave = Completer<void>();
      final update = c.applyUpdate();
      await c.applyUpdate();
      expect(c.updating, isTrue);
      expect(c.updateError, isNull);
      expect(browser.reloads, 0);
      browser.pendingSave!.complete();
      await update;
      expect(browser.reloads, 1);
      expect(browser.draft!.form.subject, 'Сохранить перед обновлением');
      c.dispose();
    },
  );
  test(
    'geometry accepts territory boundaries but rejects holes and points outside',
    () {
      expect(coversPoint(polygon, 72.6, 61.1), isTrue);
      expect(coversPoint(polygon, 72, 61), isTrue);
      expect(coversPoint(polygon, 72.7, 61.75), isTrue);
      expect(coversPoint(polygon, 72.75, 61.75), isFalse);
      expect(coversPoint(polygon, 70, 61), isFalse);
    },
  );

  test(
    'recipient auto-selection does not choose a work type and map rejects wrong points',
    () async {
      final browser = MemoryBrowser();
      final c = SignalController(
        api: SignalApi(
          origin: browser.location,
          client: MockClient(
            (request) async => json(
              request.url.path.endsWith('/catalog') ? catalogJson : emptyWall,
            ),
          ),
        ),
        browser: browser,
      );
      await c.initialize();
      expect(c.form.organizationId, organizationId);
      expect(c.form.addressId, addressId);
      expect(c.form.toJson()['category'], '');
      expect(c.form.located, isFalse);
      c.selectPoint(70, 61);
      expect(c.form.located, isFalse);
      expect(c.error, contains('внутри'));
      c.selectPoint(72.6, 61.1);
      expect(c.form.located, isTrue);
      c.nextStep();
      expect(c.step, 2);
      c.dispose();
    },
  );

  test(
    'dropped photos persist in the draft and enforce the total limit',
    () async {
      final browser = MemoryBrowser();
      final c = SignalController(
        browser: browser,
        api: SignalApi(
          origin: browser.location,
          client: MockClient(
            (request) async => json(
              request.url.path.endsWith('/catalog') ? catalogJson : emptyWall,
            ),
          ),
        ),
      );
      await c.initialize();
      c.beginPhotoDrop();
      expect(c.preparing, isTrue);
      await c.finishPhotoDrop([photo(), photo()]);
      expect(c.preparing, isFalse);
      expect(c.photos.length, 2);
      expect(browser.draft!.photos.length, 2);
      c.beginPhotoDrop();
      await c.finishPhotoDrop([photo(), photo()]);
      expect(c.photos.length, 2);
      expect(c.error, contains('трёх'));
      expect(c.preparing, isFalse);
      c.beginPhotoDrop();
      c.failPhotoDrop('Не удалось прочитать фотографию');
      expect(c.preparing, isFalse);
      expect(c.photos.length, 2);
      c.dispose();
    },
  );

  test('a subject-only draft survives and opens the questionnaire', () async {
    final browser = MemoryBrowser()
      ..draft = AppealDraft(
        form: AppealForm(subject: 'Сломана скамейка'),
        photos: [],
      );
    final c = SignalController(
      api: SignalApi(
        origin: browser.location,
        client: MockClient(
          (request) async => json(
            request.url.path.endsWith('/catalog') ? catalogJson : emptyWall,
          ),
        ),
      ),
      browser: browser,
    );
    await c.initialize();
    expect(c.form.subject, 'Сломана скамейка');
    expect(c.tab, 1);
    expect(c.step, 2);
    c.dispose();
  });

  test(
    'subject and photos are submitted once and an uncertain receipt is recovered without a duplicate',
    () async {
      final browser = MemoryBrowser()
        ..draft = AppealDraft(form: validForm(), photos: [photo()]);
      var uploads = 0, sessions = 0;
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/catalog')) return json(catalogJson);
        if (request.url.path.endsWith('/wall')) return json(emptyWall);
        if (request.url.path.endsWith('/sessions')) {
          sessions++;
          return json({'token': 'stable-token'}, 201);
        }
        if (request.url.path.endsWith('/submissions')) {
          uploads++;
          expect(request.headers['X-Capture-Token'], 'stable-token');
          expect(request.body, contains('Не убрана детская площадка'));
          expect(request.body, contains('"category":""'));
          expect(browser.draft!.pending, isTrue);
          return json({'detail': 'Ответ сервера задерживается'}, 503);
        }
        return json({
          'expired': false,
          'submitted': {'number': 'ОБ-000042'},
        });
      });
      final c = SignalController(
        api: SignalApi(origin: browser.location, client: client),
        browser: browser,
      );
      await c.initialize();
      await c.submit();
      expect(c.pending, isTrue);
      expect(c.photos, hasLength(1));
      await c.submit();
      expect(c.receipt, 'ОБ-000042');
      expect(c.pending, isFalse);
      expect(uploads, 1);
      expect(sessions, 1);
      expect(browser.draft!.receipt, 'ОБ-000042');
      c.dispose();
    },
  );

  test(
    'a failed resume preserves the frozen payload from an old draft without a subject',
    () async {
      final form = validForm()..subject = '';
      final browser = MemoryBrowser()
        ..draft = AppealDraft(
          form: form,
          photos: [photo()],
          token: 'old-token',
          pending: true,
        );
      final c = SignalController(
        api: SignalApi(
          origin: browser.location,
          client: MockClient((request) async {
            if (request.url.path.endsWith('/catalog')) return json(catalogJson);
            if (request.url.path.endsWith('/wall')) return json(emptyWall);
            return json({'detail': 'Сервер недоступен'}, 503);
          }),
        ),
        browser: browser,
      );
      await c.initialize();
      await c.submit();
      expect(c.pending, isTrue);
      expect(c.form.subject, '');
      c.changeText(subject: 'Новое');
      expect(c.form.subject, '');
      c.dispose();
    },
  );
}

class _UpdateBrowser extends MemoryBrowser {
  bool failSave = false;
  int reloads = 0;
  Completer<void>? pendingSave;
  @override
  Future<void> saveDraft(AppealDraft value) async {
    if (failSave) throw StateError('storage unavailable');
    await pendingSave?.future;
    await super.saveDraft(value);
  }

  @override
  void reload() => reloads++;
}
