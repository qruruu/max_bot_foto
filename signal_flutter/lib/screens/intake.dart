import 'package:flutter/material.dart';
import '../controller.dart';
import '../theme.dart';
import '../widgets/common.dart';

class IntakeScreen extends StatefulWidget {
  const IntakeScreen({super.key, required this.controller});
  final SignalController controller;
  @override
  State<IntakeScreen> createState() => _IntakeScreenState();
}

class _IntakeScreenState extends State<IntakeScreen> {
  final _formKey = GlobalKey<FormState>();
  final _subjectAnchor = GlobalKey(),
      _descriptionAnchor = GlobalKey(),
      _photosAnchor = GlobalKey();
  bool _attempted = false;

  void _submit(SignalController c) {
    if (c.pending) {
      c.submit();
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() => _attempted = true);
    final valid = _formKey.currentState?.validate() ?? false;
    GlobalKey? target;
    if (c.form.subject.trim().isEmpty) {
      target = _subjectAnchor;
    } else if (c.form.description.trim().isEmpty) {
      target = _descriptionAnchor;
    } else if (c.photos.isEmpty) {
      target = _photosAnchor;
    }
    if (target != null) {
      _reveal(target);
    } else if (!c.form.located) {
      c.backStep();
    } else if (valid) {
      c.submit();
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final desktop = isDesktop(context);
    return ListView(
      key: ValueKey('intake-step-${c.step}'),
      padding: EdgeInsets.fromLTRB(
        desktop ? 40 : 16,
        desktop ? 12 : 17,
        desktop ? 40 : 16,
        24,
      ),
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'НОВОЕ ОБРАЩЕНИЕ',
              style: TextStyle(
                fontSize: 10,
                letterSpacing: 1,
                color: Color(0xff597a68),
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'ШАГ ${c.step} ИЗ 2',
              style: const TextStyle(
                fontSize: 10,
                letterSpacing: .7,
                color: Color(0xff597a68),
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        const SizedBox(height: 7),
        ClipRRect(
          borderRadius: BorderRadius.circular(5),
          child: LinearProgressIndicator(
            value: c.step == 1 ? (desktop ? .5 : .44) : .8,
            minHeight: 6,
            color: green,
            backgroundColor: const Color(0xffe2ece3),
            semanticsLabel: 'Шаг ${c.step} из 2',
          ),
        ),
        SizedBox(height: desktop ? 12 : 16),
        if (c.step == 2) ...[
          Material(
            color: const Color(0xffeaf3eb),
            borderRadius: BorderRadius.circular(10),
            child: InkWell(
              onTap: c.locked ? null : c.backStep,
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding: EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: desktop ? 8 : 12,
                ),
                child: Row(
                  children: [
                    const Icon(Icons.arrow_back, size: 18, color: green),
                    const SizedBox(width: 9),
                    Expanded(
                      child: Text(
                        c.form.address.isEmpty
                            ? 'Выбрать место'
                            : c.form.address,
                        style: const TextStyle(fontSize: 14, color: green),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          SizedBox(height: desktop ? 10 : 15),
        ],
        Text(
          c.step == 1
              ? (desktop ? 'Выберите место' : 'Сообщить о проблеме')
              : 'Расскажите о проблеме',
          style: Theme.of(context).textTheme.headlineSmall?.copyWith(
            fontSize: desktop ? 28 : 25,
            color: desktop ? desktopInk : ink,
          ),
        ),
        SizedBox(height: desktop ? 12 : 17),
        if (c.restored)
          Notice(
            'Восстановили ваш черновик${c.photos.isEmpty ? '' : ' вместе с фотографиями'}.',
            icon: Icons.restore,
          ),
        if (c.pending)
          const Notice(
            'Проверяем, получено ли обращение. Повторная попытка не создаст дубль.',
            icon: Icons.sync,
          ),
        if (c.step == 1) _PlaceStep(controller: c) else _descriptionStep(c),
        if (c.error != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Notice(c.error!, error: true),
          ),
      ],
    );
  }

  Widget _descriptionStep(SignalController c) {
    final desktop = isDesktop(context);
    final fields = <Widget>[
      if (!c.form.located && !c.pending)
        const Notice(
          'Сначала выберите территорию и отметьте место на карте.',
          error: true,
        ),
      FieldLabel('Тема обращения', key: _subjectAnchor, required: true),
      TextFormField(
        key: const ValueKey('subject'),
        initialValue: c.form.subject,
        maxLength: 80,
        enabled: !c.locked,
        textCapitalization: TextCapitalization.sentences,
        style: TextStyle(
          fontSize: desktop ? 12.5 : 14,
          height: desktop ? 1.3 : null,
        ),
        decoration: const InputDecoration(
          hintText: 'Кратко сформулируйте проблему',
          helperText: 'Например, не убрана детская площадка',
          helperMaxLines: 2,
          helperStyle: TextStyle(fontSize: 10.5, color: muted),
        ),
        onChanged: (value) => c.changeText(subject: value),
        validator: (value) => c.pending || (value?.trim().isNotEmpty ?? false)
            ? null
            : 'Укажите тему обращения',
      ),
      const SizedBox(height: 15),
      FieldLabel('Описание', key: _descriptionAnchor, required: true),
      TextFormField(
        key: const ValueKey('description'),
        initialValue: c.form.description,
        minLines: 5,
        maxLines: 10,
        maxLength: 4000,
        enabled: !c.locked,
        textCapitalization: TextCapitalization.sentences,
        style: TextStyle(fontSize: desktop ? 12.5 : 14, height: 1.5),
        decoration: const InputDecoration(
          hintText: 'Что произошло и что нужно исправить?',
        ),
        onChanged: (value) => c.changeText(description: value),
        validator: (value) => c.pending || (value?.trim().isNotEmpty ?? false)
            ? null
            : 'Опишите проблему',
      ),
    ];
    final attachments = <Widget>[
      const FieldLabel('Уточнение места', optional: true),
      TextFormField(
        initialValue: c.form.place,
        enabled: !c.locked,
        maxLength: 300,
        style: TextStyle(
          fontSize: desktop ? 12.5 : 14,
          height: desktop ? 1.3 : null,
        ),
        decoration: const InputDecoration(
          hintText: 'Например, рядом со вторым подъездом',
          counterText: '',
        ),
        onChanged: (value) => c.changeText(place: value),
      ),
      SizedBox(height: desktop ? 14 : 21),
      Row(
        key: _photosAnchor,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            'Фотографии',
            style: TextStyle(
              fontSize: desktop ? 15 : 17,
              fontWeight: FontWeight.w600,
            ),
          ),
          Text(
            '${c.photos.length} / 3',
            style: const TextStyle(fontSize: 12, color: muted),
          ),
        ],
      ),
      SizedBox(height: desktop ? 8 : 10),
      _ValidationHighlight(
        error: _attempted && c.photos.isEmpty
            ? 'Добавьте хотя бы одну фотографию'
            : null,
        child: desktop
            ? c.browser.photoDropTarget(
                remaining: 3 - c.photos.length,
                enabled: !c.locked && c.photos.length < 3,
                onStart: c.beginPhotoDrop,
                onPhotos: c.finishPhotoDrop,
                onError: c.failPhotoDrop,
                child: _Photos(controller: c, desktop: true),
              )
            : _Photos(controller: c),
      ),
      SizedBox(height: desktop ? 14 : 20),
      const FieldLabel('Телефон или электронная почта', optional: true),
      TextFormField(
        initialValue: c.form.contact,
        enabled: !c.locked,
        maxLength: 200,
        style: TextStyle(
          fontSize: desktop ? 12.5 : 14,
          height: desktop ? 1.3 : null,
        ),
        keyboardType: TextInputType.text,
        decoration: const InputDecoration(
          hintText: 'Для уточнения обращения',
          counterText: '',
        ),
        onChanged: (value) => c.changeText(contact: value),
      ),
      const SizedBox(height: 10),
      if (!desktop)
        const Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              Icons.verified_user_outlined,
              size: 14,
              color: Color(0xff6d8574),
            ),
            SizedBox(width: 6),
            Expanded(
              child: Text(
                'Контакты видны только администратору организации.',
                style: TextStyle(fontSize: 10.5, color: muted, height: 1.5),
              ),
            ),
          ],
        ),
      if (!desktop) const SizedBox(height: 8),
      if (!desktop)
        const Text(
          'Тема, описание и фотографии появятся на стене города. Не добавляйте в них личные данные.',
          style: TextStyle(fontSize: 10.5, color: muted, height: 1.5),
        ),
      SizedBox(height: desktop ? 12 : 18),
      SizedBox(
        width: double.infinity,
        child: FilledButton(
          style: desktop
              ? FilledButton.styleFrom(minimumSize: const Size(0, 40))
              : null,
          onPressed: c.busy || c.preparing ? null : () => _submit(c),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (c.busy) ...[
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(width: 9),
              ],
              Text(
                c.busy
                    ? 'Отправляем…'
                    : c.pending
                    ? 'Проверить отправку'
                    : 'Отправить обращение',
              ),
            ],
          ),
        ),
      ),
    ];
    final form = Form(
      key: _formKey,
      autovalidateMode: _attempted
          ? AutovalidateMode.onUserInteraction
          : AutovalidateMode.disabled,
      child: desktop
          ? Row(
              key: const ValueKey('desktop-description-columns'),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  flex: 54,
                  child: SectionCard(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: fields,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  flex: 46,
                  child: SectionCard(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: attachments,
                    ),
                  ),
                ),
              ],
            )
          : SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ...fields,
                  const SizedBox(height: 15),
                  ...attachments,
                ],
              ),
            ),
    );
    if (!desktop) return form;
    return Theme(
      data: Theme.of(context).copyWith(
        inputDecorationTheme: Theme.of(context).inputDecorationTheme.copyWith(
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 12,
            vertical: 8,
          ),
          hintStyle: const TextStyle(
            color: Color(0xff929b98),
            fontSize: 12,
            fontWeight: FontWeight.w400,
            height: 1.3,
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          form,
          const Padding(
            padding: EdgeInsets.only(top: 10, left: 2),
            child: Text(
              'Контакты видны только администратору. Тема, описание и фотографии появятся на стене города.',
              style: TextStyle(fontSize: 10.5, height: 1.4, color: muted),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlaceStep extends StatefulWidget {
  const _PlaceStep({required this.controller});
  final SignalController controller;
  @override
  State<_PlaceStep> createState() => _PlaceStepState();
}

class _PlaceStepState extends State<_PlaceStep> {
  bool _attempted = false;
  final _organization = GlobalKey(),
      _territory = GlobalKey(),
      _map = GlobalKey();
  @override
  Widget build(BuildContext context) {
    final c = widget.controller, recipient = c.recipient;
    final desktop = isDesktop(context);
    final selection = <Widget>[
      _ValidationHighlight(
        key: _organization,
        error: _attempted && recipient == null ? 'Выберите организацию' : null,
        child: ChoiceField(
          label: 'Организация',
          options: c.organizations.map((o) => (o.id, o.name)).toList(),
          value: c.form.organizationId,
          enabled: !c.locked,
          compact: desktop,
          placeholder: 'Выберите организацию',
          onChanged: c.selectOrganization,
        ),
      ),
      if (recipient != null) ...[
        const SizedBox(height: 17),
        _ValidationHighlight(
          key: _territory,
          error: _attempted && c.address == null ? 'Выберите территорию' : null,
          child: ChoiceField(
            label: 'Территория',
            options: recipient.addresses
                .map((a) => (a['id'] as String, a['label'] as String))
                .toList(),
            value: c.form.addressId,
            enabled: !c.locked,
            compact: desktop,
            placeholder: 'Выберите территорию',
            onChanged: c.selectAddress,
          ),
        ),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.verified_user_outlined,
              size: 18,
              color: Color(0xff648571),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                recipient.addresses.isEmpty
                    ? 'У организации пока нет активных территорий на карте.'
                    : 'Выберите территорию этой организации и отметьте на карте место проблемы.',
                style: const TextStyle(
                  fontSize: 11.5,
                  height: 1.6,
                  color: Color(0xff647b6b),
                ),
              ),
            ),
          ],
        ),
      ],
      if (c.organizations.isEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 15),
          child: Text(
            c.form.city.isEmpty
                ? 'Сначала выберите город вверху страницы.'
                : 'В этом городе пока нет организаций, принимающих обращения.',
            style: const TextStyle(fontSize: 13, color: muted),
          ),
        ),
    ];
    final next = SizedBox(
      width: double.infinity,
      child: FilledButton(
        style: desktop
            ? FilledButton.styleFrom(minimumSize: const Size(0, 40))
            : null,
        onPressed: c.locked
            ? null
            : () {
                if (c.form.located) {
                  c.nextStep();
                  return;
                }
                setState(() => _attempted = true);
                _reveal(
                  recipient == null
                      ? _organization
                      : c.address == null
                      ? _territory
                      : _map,
                );
              },
        child: const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text('Далее'),
            SizedBox(width: 9),
            Icon(Icons.arrow_forward, size: 18),
          ],
        ),
      ),
    );
    if (desktop) {
      return Row(
        key: const ValueKey('desktop-place-columns'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 42,
            child: SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [...selection, const SizedBox(height: 28), next],
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            flex: 58,
            child: _ValidationHighlight(
              key: _map,
              error: _attempted && c.address != null && !c.form.located
                  ? 'Отметьте место проблемы на карте'
                  : null,
              child: _PlaceMap(controller: c, desktop: true),
            ),
          ),
        ],
      );
    }
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ...selection,
          if (recipient != null && c.address != null) ...[
            const SizedBox(height: 15),
            _ValidationHighlight(
              key: _map,
              error: _attempted && !c.form.located
                  ? 'Отметьте место проблемы на карте'
                  : null,
              child: _PlaceMap(controller: c),
            ),
          ],
          const SizedBox(height: 20),
          next,
        ],
      ),
    );
  }
}

void _reveal(GlobalKey key) {
  WidgetsBinding.instance.addPostFrameCallback((_) {
    final context = key.currentContext;
    if (context != null && context.mounted) {
      Scrollable.ensureVisible(
        context,
        alignment: .12,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    }
  });
}

class _ValidationHighlight extends StatelessWidget {
  const _ValidationHighlight({super.key, required this.child, this.error});
  final Widget child;
  final String? error;
  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.error;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: double.infinity,
          decoration: BoxDecoration(
            border: error == null ? null : Border.all(color: color, width: 1.5),
            borderRadius: BorderRadius.circular(10),
          ),
          padding: error == null ? EdgeInsets.zero : const EdgeInsets.all(5),
          child: child,
        ),
        if (error != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Semantics(
              liveRegion: true,
              child: Text(error!, style: TextStyle(color: color, fontSize: 12)),
            ),
          ),
      ],
    );
  }
}

class _PlaceMap extends StatelessWidget {
  const _PlaceMap({required this.controller, this.desktop = false});
  final SignalController controller;
  final bool desktop;
  @override
  Widget build(BuildContext context) {
    final c = controller, address = controller.address;
    final waiting = address == null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: desktop ? 284 : 300,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Stack(
              children: [
                Positioned.fill(
                  child: IgnorePointer(
                    ignoring: c.locked || waiting,
                    child: c.browser.map(
                      apiKey: c.catalog?.mapKey ?? '',
                      organizations: c.organizations,
                      organizationId: c.recipient?.id ?? '',
                      overview: waiting,
                      districtId: address?['district_id'] as int?,
                      longitude: c.form.longitude,
                      latitude: c.form.latitude,
                      onPoint: waiting ? null : c.selectPoint,
                    ),
                  ),
                ),
                if (waiting)
                  Positioned.fill(
                    child: MapSafe(
                      child: ColoredBox(
                        color: const Color(0xb8f6f9f7),
                        child: const Center(
                          child: Padding(
                            padding: EdgeInsets.all(24),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.location_on_outlined,
                                  size: 34,
                                  color: Color(0xff63737b),
                                ),
                                SizedBox(height: 12),
                                Text(
                                  'Выберите территорию,\nчтобы открыть карту',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600,
                                    color: desktopInk,
                                  ),
                                ),
                                SizedBox(height: 8),
                                Text(
                                  'После выбора территории здесь отобразится карта с границами\nи возможностью отметить место проблемы.',
                                  textAlign: TextAlign.center,
                                  style: TextStyle(
                                    fontSize: 11.5,
                                    height: 1.5,
                                    color: muted,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
        if (!waiting) ...[
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.location_on,
                size: 19,
                color: c.form.located ? green : const Color(0xff8a805c),
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  c.form.located
                      ? 'Место отмечено. Можно описать проблему.'
                      : 'Отметьте место проблемы на карте.',
                  style: TextStyle(
                    fontSize: 12,
                    color: c.form.located ? green : const Color(0xff758271),
                    height: 1.5,
                  ),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _Photos extends StatelessWidget {
  const _Photos({required this.controller, this.desktop = false});
  final bool desktop;
  final SignalController controller;
  @override
  Widget build(BuildContext context) {
    final c = controller;
    Widget add() => CustomPaint(
      painter: _DashedBorder(),
      child: Material(
        color: const Color(0xfff0f7ef),
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          onTap: c.locked ? null : c.addPhotos,
          borderRadius: BorderRadius.circular(10),
          child: desktop && c.photos.isEmpty
              ? const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.add_photo_alternate_outlined,
                        size: 28,
                        color: Color(0xff637981),
                      ),
                      SizedBox(width: 14),
                      Flexible(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Перетащите фотографии сюда',
                              style: TextStyle(
                                fontSize: 11.5,
                                color: desktopInk,
                              ),
                            ),
                            SizedBox(height: 3),
                            Text(
                              'или нажмите, чтобы выбрать файлы',
                              style: TextStyle(fontSize: 10, color: muted),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                )
              : const Padding(
                  padding: EdgeInsets.all(12),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.add_photo_alternate_outlined,
                        color: Color(0xff4b805c),
                        size: 29,
                      ),
                      SizedBox(height: 7),
                      Text(
                        'Добавить фото',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 13,
                          color: Color(0xff427553),
                        ),
                      ),
                    ],
                  ),
                ),
        ),
      ),
    );
    if (c.preparing) {
      return SizedBox(
        height: desktop ? 56 : 106,
        child: const Center(child: CircularProgressIndicator(strokeWidth: 2)),
      );
    }
    if (c.photos.isEmpty) {
      return SizedBox(
        width: double.infinity,
        height: desktop ? 56 : 106,
        child: add(),
      );
    }
    return LayoutBuilder(
      builder: (context, size) {
        final width = desktop
            ? ((size.maxWidth - 16) / 3).clamp(64.0, 110.0)
            : (size.maxWidth - 16) / 3;
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ...c.photos.asMap().entries.map(
              (entry) => SizedBox(
                width: width,
                height: width,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Semantics(
                        label: 'Фото ${entry.key + 1}',
                        image: true,
                        child: InkWell(
                          onTap: () => showDialog<void>(
                            context: context,
                            builder: (context) => Dialog(
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Flexible(
                                    child: InteractiveViewer(
                                      child: Image.memory(
                                        entry.value.preview,
                                        fit: BoxFit.contain,
                                        errorBuilder: (_, _, _) => const Padding(
                                          padding: EdgeInsets.all(24),
                                          child: Text(
                                            'Оригинал фотографии будет обработан при отправке.',
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                  TextButton(
                                    onPressed: () => Navigator.pop(context),
                                    child: const Text('Закрыть'),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          child: Image.memory(
                            entry.value.preview,
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) => const ColoredBox(
                              color: paleGreen,
                              child: Icon(Icons.image_outlined, color: muted),
                            ),
                          ),
                        ),
                      ),
                      Positioned(
                        top: 2,
                        right: 2,
                        child: SizedBox(
                          width: 30,
                          height: 30,
                          child: IconButton.filledTonal(
                            padding: EdgeInsets.zero,
                            tooltip: 'Удалить фото ${entry.key + 1}',
                            onPressed: c.locked
                                ? null
                                : () => c.removePhoto(entry.value.id),
                            style: IconButton.styleFrom(
                              backgroundColor: const Color(0xe6ffffff),
                            ),
                            icon: const Icon(Icons.delete_outline, size: 16),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (c.photos.length < 3)
              SizedBox(width: width, height: width, child: add()),
          ],
        );
      },
    );
  }
}

class _DashedBorder extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..addRRect(
        RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(10)),
      );
    final paint = Paint()
      ..color = const Color(0xffaec8b4)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (final metric in path.computeMetrics()) {
      for (double start = 0; start < metric.length; start += 9) {
        canvas.drawPath(metric.extractPath(start, start + 5), paint);
      }
    }
  }

  @override
  bool shouldRepaint(_DashedBorder oldDelegate) => false;
}
