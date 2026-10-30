import 'package:flutter/material.dart';
import '../browser.dart';
import '../models.dart';
import '../theme.dart';
import 'common.dart';

class AppealCard extends StatefulWidget {
  const AppealCard({
    super.key,
    required this.appeal,
    required this.browser,
    required this.origin,
  });
  final Appeal appeal;
  final SignalBrowser browser;
  final Uri origin;
  @override
  State<AppealCard> createState() => _AppealCardState();
}

class _AppealCardState extends State<AppealCard> {
  bool expanded = false;

  Future<void> copy() async {
    final value =
        widget.appeal.shareUrl ??
        widget.origin.resolve('/a/${widget.appeal.id}').toString();
    try {
      await widget.browser.copy(value);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Ссылка скопирована'),
          duration: Duration(seconds: 2),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Скопируйте ссылку'),
          content: SelectableText(value),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Закрыть'),
            ),
          ],
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final item = widget.appeal;
      // The reference card is 512 px wide. Keep its proportions on phones.
      final scale = (constraints.maxWidth / 512).clamp(.67, 1.0);
      final title = item.subject.isNotEmpty
          ? item.subject
          : item.description.split('\n').first;
      return DefaultTextStyle.merge(
        style: TextStyle(
          fontFamily: 'Roboto',
          fontSize: 18 * scale,
          height: 4 / 3,
          color: const Color(0xff171a18),
          letterSpacing: 0,
        ),
        child: GestureDetector(
          onLongPress: copy,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: const Color(0xfffffdfb),
              border: Border.all(color: const Color(0xffeeece8)),
              borderRadius: BorderRadius.circular(21 * scale),
            ),
            child: Padding(
              padding: EdgeInsets.fromLTRB(
                16 * scale,
                21 * scale,
                16 * scale,
                20 * scale,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 6 * scale),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                '${item.number} · ${formatDate(item.createdAt)}',
                                style: TextStyle(
                                  color: const Color(0xff828a93),
                                  fontSize: 18 * scale,
                                  height: 1.25,
                                ),
                              ),
                            ),
                            SizedBox(width: 8 * scale),
                            StatusBadge(status: item.status, scale: scale),
                          ],
                        ),
                        SizedBox(height: 10 * scale),
                        Text(
                          title,
                          style: TextStyle(
                            fontSize: 24 * scale,
                            height: 1.25,
                            fontWeight: FontWeight.w700,
                            letterSpacing: .25 * scale,
                            color: const Color(0xff111512),
                          ),
                        ),
                      ],
                    ),
                  ),
                  SizedBox(height: 8 * scale),
                  Padding(
                    padding: EdgeInsets.only(left: 6 * scale),
                    child: _ComplaintBody(
                      appeal: item,
                      origin: widget.origin,
                      scale: scale,
                      expanded: expanded,
                      onToggle: () => setState(() => expanded = !expanded),
                    ),
                  ),
                  if (item.response != null) ...[
                    SizedBox(height: 27 * scale),
                    Padding(
                      padding: EdgeInsets.symmetric(horizontal: 2 * scale),
                      child: _OrganizationResponse(
                        appeal: item,
                        origin: widget.origin,
                        scale: scale,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      );
    },
  );
}

class _ComplaintBody extends StatelessWidget {
  const _ComplaintBody({
    required this.appeal,
    required this.origin,
    required this.scale,
    required this.expanded,
    required this.onToggle,
  });
  final Appeal appeal;
  final Uri origin;
  final double scale;
  final bool expanded;
  final VoidCallback onToggle;
  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Expanded(
        child: Padding(
          padding: EdgeInsets.only(top: 4 * scale),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _AddressLine(text: appeal.address, scale: scale),
              if (appeal.place.isNotEmpty)
                Padding(
                  padding: EdgeInsets.only(left: 28 * scale, top: 3 * scale),
                  child: Text(
                    appeal.place,
                    style: TextStyle(
                      fontSize: 16 * scale,
                      color: const Color(0xff646963),
                    ),
                  ),
                ),
              if (appeal.subject.isNotEmpty ||
                  appeal.description.contains('\n')) ...[
                SizedBox(height: 14 * scale),
                AppealDescription(
                  text: appeal.description,
                  scale: scale,
                  expanded: expanded,
                  onToggle: onToggle,
                ),
              ],
              if (appeal.response == null)
                Padding(
                  padding: EdgeInsets.only(top: 10 * scale),
                  child: Text(
                    appeal.organization,
                    style: TextStyle(
                      fontSize: 16 * scale,
                      color: const Color(0xff356342),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
      if (appeal.photos.isNotEmpty) ...[
        SizedBox(width: 20 * scale),
        PhotoThumbnail(photos: appeal.photos, origin: origin, scale: scale),
      ],
    ],
  );
}

class _AddressLine extends StatelessWidget {
  const _AddressLine({required this.text, required this.scale});
  final String text;
  final double scale;
  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Transform.translate(
        offset: Offset(-3 * scale, 0),
        child: Icon(
          Icons.location_on_outlined,
          size: 24 * scale,
          color: const Color(0xff666d70),
        ),
      ),
      SizedBox(width: 4 * scale),
      Expanded(
        child: Text(
          text,
          style: TextStyle(
            fontSize: 18 * scale,
            height: 1.5,
            color: const Color(0xff4d5350),
          ),
        ),
      ),
    ],
  );
}

class AppealDescription extends StatelessWidget {
  const AppealDescription({
    super.key,
    required this.text,
    required this.scale,
    required this.expanded,
    required this.onToggle,
  });
  final String text;
  final double scale;
  final bool expanded;
  final VoidCallback onToggle;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final style = DefaultTextStyle.of(context).style.copyWith(
        fontSize: 17 * scale,
        height: 24 / 17,
        color: const Color(0xff62635f),
      );
      final measurement = TextPainter(
        text: TextSpan(text: text, style: style),
        textDirection: Directionality.of(context),
        textScaler: MediaQuery.textScalerOf(context),
        maxLines: 3,
        ellipsis: '…',
      )..layout(maxWidth: constraints.maxWidth);
      final truncated = measurement.didExceedMaxLines;
      var preview = text;
      if (truncated) {
        final lastLine = measurement.computeLineMetrics().last;
        var end = measurement
            .getPositionForOffset(
              Offset(constraints.maxWidth, lastLine.baseline),
            )
            .offset;
        final visibleEnd = end;
        final lastLineStart = measurement
            .getPositionForOffset(Offset(0, lastLine.baseline))
            .offset;
        // Keep complete words when possible, including long unbroken complaints.
        while (end > lastLineStart &&
            end < text.length &&
            !RegExp(r'\s').hasMatch(text[end])) {
          end--;
        }
        if (end <= lastLineStart) end = visibleEnd;
        preview =
            '${text.substring(0, end).replaceFirst(RegExp(r'[\s.,;:!?]+$'), '')}…';
      }
      measurement.dispose();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            expanded ? text : preview,
            style: style,
            maxLines: expanded ? null : 3,
            overflow: expanded ? TextOverflow.visible : TextOverflow.ellipsis,
          ),
          if (truncated) ...[
            SizedBox(height: 6 * scale),
            InkWell(
              onTap: onToggle,
              child: Text(
                expanded ? 'Свернуть' : 'Читать полностью',
                style: TextStyle(
                  fontSize: 18 * scale,
                  height: 4 / 3,
                  fontWeight: FontWeight.w700,
                  color: const Color(0xff315c3b),
                  decoration: TextDecoration.underline,
                  decorationColor: const Color(0xff315c3b),
                ),
              ),
            ),
          ],
        ],
      );
    },
  );
}

class _OrganizationResponse extends StatelessWidget {
  const _OrganizationResponse({
    required this.appeal,
    required this.origin,
    required this.scale,
  });
  final Appeal appeal;
  final Uri origin;
  final double scale;
  @override
  Widget build(BuildContext context) {
    final response = appeal.response!;
    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(
        17 * scale,
        18 * scale,
        17 * scale,
        24 * scale,
      ),
      decoration: BoxDecoration(
        color: const Color(0xfff0f5e9),
        borderRadius: BorderRadius.circular(20 * scale),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: 'Ответ организации · ${appeal.organization}',
                      ),
                      WidgetSpan(
                        alignment: PlaceholderAlignment.middle,
                        child: Padding(
                          padding: EdgeInsets.only(left: 10 * scale),
                          child: Icon(
                            Icons.verified,
                            color: const Color(0xff2f7237),
                            size: 21 * scale,
                          ),
                        ),
                      ),
                    ],
                  ),
                  style: TextStyle(
                    color: const Color(0xff346338),
                    fontSize: 17.5 * scale,
                    height: 22 / 17.5,
                  ),
                ),
              ),
              SizedBox(width: 14 * scale),
              Text(
                formatDate(response.at),
                style: TextStyle(
                  color: const Color(0xff596255),
                  fontSize: 15.5 * scale,
                  height: 22 / 15.5,
                ),
              ),
            ],
          ),
          SizedBox(height: 12 * scale),
          Text(
            response.comment,
            style: TextStyle(
              color: const Color(0xff151914),
              fontSize: 18 * scale,
              height: 4 / 3,
            ),
          ),
          if (response.photos.isNotEmpty)
            Padding(
              padding: EdgeInsets.only(top: 10 * scale),
              child: TextButton.icon(
                onPressed: () => openPhotos(context, response.photos, origin),
                style: TextButton.styleFrom(
                  padding: EdgeInsets.zero,
                  minimumSize: const Size(0, 32),
                ),
                icon: const Icon(Icons.camera_alt_outlined, size: 16),
                label: Text('Фото ответа (${response.photos.length})'),
              ),
            ),
        ],
      ),
    );
  }
}

class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.status, this.scale = 1});
  final String status;
  final double scale;
  @override
  Widget build(BuildContext context) {
    final (background, foreground) = switch (status) {
      'NEW' => (const Color(0xffe5f0fd), const Color(0xff1746b0)),
      'DECLINED' ||
      'REJECTED' => (const Color(0xfff7e6df), const Color(0xff915642)),
      'RESOLVED' ||
      'COMPLETED' => (const Color(0xffe6f2df), const Color(0xff3b6933)),
      'ASSIGNED' ||
      'IN_PROGRESS' => (const Color(0xffe5f1df), const Color(0xff2c5d28)),
      _ => (const Color(0xffeaf0f5), const Color(0xff576b83)),
    };
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: 14 * scale,
        vertical: 5 * scale,
      ),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(18 * scale),
      ),
      child: Text(
        appealStatuses[status] ?? status,
        style: TextStyle(
          fontFamily: 'Roboto',
          fontSize: 18 * scale,
          height: 22 / 18,
          fontWeight: FontWeight.w400,
          color: foreground,
        ),
      ),
    );
  }
}

class PhotoThumbnail extends StatelessWidget {
  const PhotoThumbnail({
    super.key,
    required this.photos,
    required this.origin,
    this.scale = 1,
    this.size,
  });
  final Size? size;
  final List<AppealPhoto> photos;
  final Uri origin;
  final double scale;
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Открыть фотографии обращения: ${photos.length}',
    button: true,
    child: InkWell(
      onTap: () => openPhotos(context, photos, origin),
      borderRadius: BorderRadius.circular(13 * scale),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(13 * scale),
        child: SizedBox(
          width: size?.width ?? 128 * scale,
          height: size?.height ?? 145 * scale,
          child: Image.network(
            origin.resolve(photos.first.previewUrl).toString(),
            fit: BoxFit.cover,
            errorBuilder: (_, _, _) => const ColoredBox(
              color: Color(0xffe2ece4),
              child: Icon(Icons.image_outlined, color: muted),
            ),
          ),
        ),
      ),
    ),
  );
}

Future<void> openPhotos(
  BuildContext context,
  List<AppealPhoto> photos,
  Uri origin,
) => showDialog<void>(
  context: context,
  builder: (context) => MapSafe(
    child: _PhotoGallery(photos: photos, origin: origin),
  ),
);

class _PhotoGallery extends StatefulWidget {
  const _PhotoGallery({required this.photos, required this.origin});
  final List<AppealPhoto> photos;
  final Uri origin;
  @override
  State<_PhotoGallery> createState() => _PhotoGalleryState();
}

class _PhotoGalleryState extends State<_PhotoGallery> {
  final pages = PageController();
  int page = 0;
  @override
  void dispose() {
    pages.dispose();
    super.dispose();
  }

  void move(int value) => pages.animateToPage(
    value,
    duration: const Duration(milliseconds: 180),
    curve: Curves.easeOut,
  );
  @override
  Widget build(BuildContext context) => Dialog.fullscreen(
    backgroundColor: const Color(0xff15231d),
    child: SafeArea(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
            child: Row(
              children: [
                const Expanded(
                  child: Text(
                    'Фотографии обращения',
                    style: TextStyle(color: Colors.white, fontSize: 15),
                  ),
                ),
                IconButton(
                  onPressed: () => Navigator.pop(context),
                  tooltip: 'Закрыть фотографии',
                  icon: const Icon(Icons.close, color: Colors.white),
                ),
              ],
            ),
          ),
          Expanded(
            child: PageView(
              controller: pages,
              onPageChanged: (value) => setState(() => page = value),
              children: widget.photos
                  .map(
                    (photo) => InteractiveViewer(
                      child: Center(
                        child: Image.network(
                          widget.origin.resolve(photo.url).toString(),
                          fit: BoxFit.contain,
                          errorBuilder: (_, _, _) => const Text(
                            'Не удалось загрузить фото',
                            style: TextStyle(color: Colors.white),
                          ),
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(
                  tooltip: 'Предыдущее фото',
                  onPressed: page > 0 ? () => move(page - 1) : null,
                  icon: Icon(
                    Icons.chevron_left,
                    color: page > 0 ? Colors.white : Colors.white24,
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 18),
                  child: Text(
                    '${page + 1} / ${widget.photos.length}',
                    style: const TextStyle(color: Colors.white70),
                  ),
                ),
                IconButton(
                  tooltip: 'Следующее фото',
                  onPressed: page + 1 < widget.photos.length
                      ? () => move(page + 1)
                      : null,
                  icon: Icon(
                    Icons.chevron_right,
                    color: page + 1 < widget.photos.length
                        ? Colors.white
                        : Colors.white24,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}
