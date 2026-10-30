import 'package:flutter/material.dart';
import '../browser.dart';
import '../models.dart';
import '../theme.dart';
import 'appeal_card.dart';

class DesktopAppealCard extends StatefulWidget {
  const DesktopAppealCard({
    super.key,
    required this.appeal,
    required this.browser,
    required this.origin,
  });
  final Appeal appeal;
  final SignalBrowser browser;
  final Uri origin;
  @override
  State<DesktopAppealCard> createState() => _DesktopAppealCardState();
}

class _DesktopAppealCardState extends State<DesktopAppealCard> {
  bool expanded = false, responseOpen = false;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, bounds) {
      final item = widget.appeal;
      final hasSubject = item.subject.isNotEmpty;
      return DefaultTextStyle.merge(
        style: const TextStyle(
          fontFamily: 'Inter',
          color: desktopInk,
          fontSize: 12.5,
          height: 1.45,
        ),
        child: Container(
          constraints: const BoxConstraints(minHeight: 274),
          padding: const EdgeInsets.fromLTRB(18, 12, 14, 14),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: .94),
            border: Border.all(color: const Color(0xffe1e8e6)),
            borderRadius: BorderRadius.circular(11),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${item.number} · ${formatDate(item.createdAt)}',
                      style: const TextStyle(
                        fontSize: 13,
                        color: Color(0xff788393),
                      ),
                    ),
                  ),
                  StatusBadge(status: item.status, scale: .65),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          hasSubject ? item.subject : item.description,
                          maxLines: expanded ? null : 2,
                          overflow: expanded
                              ? TextOverflow.visible
                              : TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w700,
                            height: 1.2,
                            letterSpacing: -.55,
                            color: desktopInk,
                          ),
                        ),
                        const SizedBox(height: 9),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Icon(
                              Icons.location_on_outlined,
                              size: 18,
                              color: Color(0xff586773),
                            ),
                            const SizedBox(width: 5),
                            Expanded(
                              child: Text(
                                item.address,
                                style: const TextStyle(fontSize: 12.5),
                              ),
                            ),
                          ],
                        ),
                        if (item.place.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 4, left: 23),
                            child: Text(
                              item.place,
                              style: const TextStyle(
                                fontSize: 11.5,
                                color: muted,
                              ),
                            ),
                          ),
                        if (hasSubject) ...[
                          const SizedBox(height: 12),
                          AppealDescription(
                            text: item.description,
                            scale: 12.5 / 17,
                            expanded: expanded,
                            onToggle: () =>
                                setState(() => expanded = !expanded),
                          ),
                        ] else if (item.description.length > 100)
                          TextButton(
                            onPressed: () =>
                                setState(() => expanded = !expanded),
                            style: TextButton.styleFrom(
                              padding: EdgeInsets.zero,
                              minimumSize: const Size(0, 28),
                            ),
                            child: Text(
                              expanded ? 'Свернуть' : 'Читать полностью',
                              style: const TextStyle(
                                fontSize: 12,
                                decoration: TextDecoration.underline,
                              ),
                            ),
                          ),
                        const SizedBox(height: 10),
                        Text(
                          item.organization,
                          style: const TextStyle(color: green, fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                  if (item.photos.isNotEmpty) ...[
                    const SizedBox(width: 16),
                    PhotoThumbnail(
                      photos: item.photos,
                      origin: widget.origin,
                      size: Size(bounds.maxWidth < 440 ? 118 : 136, 142),
                    ),
                  ],
                ],
              ),
              if (item.response != null) ...[
                const SizedBox(height: 14),
                Material(
                  color: const Color(0xffe8f3ed),
                  borderRadius: BorderRadius.circular(8),
                  child: InkWell(
                    onTap: () => setState(() => responseOpen = !responseOpen),
                    borderRadius: BorderRadius.circular(8),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(
                            Icons.chat_bubble_outline,
                            size: 18,
                            color: green,
                          ),
                          const SizedBox(width: 9),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text.rich(
                                  TextSpan(
                                    children: [
                                      const TextSpan(
                                        text: 'Ответ организации',
                                        style: TextStyle(
                                          fontWeight: FontWeight.w500,
                                        ),
                                      ),
                                      TextSpan(
                                        text:
                                            ' · ${formatDate(item.response!.at)}',
                                        style: const TextStyle(color: muted),
                                      ),
                                    ],
                                  ),
                                  style: const TextStyle(
                                    color: green,
                                    fontSize: 12,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  item.response!.comment,
                                  maxLines: responseOpen ? null : 1,
                                  overflow: responseOpen
                                      ? TextOverflow.visible
                                      : TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 11.5,
                                    color: Color(0xff4e7467),
                                  ),
                                ),
                                if (responseOpen &&
                                    item.response!.photos.isNotEmpty)
                                  TextButton.icon(
                                    onPressed: () => openPhotos(
                                      context,
                                      item.response!.photos,
                                      widget.origin,
                                    ),
                                    icon: const Icon(
                                      Icons.camera_alt_outlined,
                                      size: 16,
                                    ),
                                    label: Text(
                                      'Фото ответа (${item.response!.photos.length})',
                                      style: const TextStyle(fontSize: 12),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 7),
                          Icon(
                            responseOpen
                                ? Icons.keyboard_arrow_up
                                : Icons.keyboard_arrow_down,
                            size: 17,
                            color: green,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      );
    },
  );
}
