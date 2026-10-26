// Public wording only: catalog codes, routing and operator labels stay unchanged.
const WORK_TYPES = new Map<string, string>([
  ['DEICING_MANUAL', 'Скользко, лёд не посыпан'],
  ['SNOW_MANUAL', 'Снег на дорожке или у входа'],
  ['BIN_EMPTYING', 'Переполненная урна'],
  ['LAWN_LITTER', 'Мусор на газоне'],
  ['DRAIN_CLEANING', 'Засорена решётка для стока воды'],
  ['METAL_CUTTING', 'Торчит арматура или труба'],
  ['PLAYGROUND_MAINTENANCE', 'Проблема на детской или спортплощадке'],
  ['UNPAVED_LITTER', 'Мусор на участке без асфальта и плитки'],
  ['SWEEPING', 'Мусор и песок на дорожках'],
  ['BIN_WASHING', 'Грязная урна'],
  ['LAWN_RAKING', 'Листья и сухая трава на газоне'],
  ['GREEN_CLEANING', 'Ветки или упавшее дерево'],
  ['GRASS_MOWING', 'Не скошена или не убрана трава'],
  ['PAVING_WASHING', 'Грязная плитка или брусчатка'],
  ['SNOW_MECHANICAL', 'Снег на проезде или большой площадке'],
  ['SNOW_REMOVAL', 'Не вывезены кучи снега'],
]);

export function citizenWorkOption(work: {code: string; name: string}) {
  return {value: work.code, label: WORK_TYPES.get(work.code) || work.name};
}
