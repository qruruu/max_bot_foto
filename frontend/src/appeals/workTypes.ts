// Public wording only: catalog codes, routing and operator labels stay unchanged.
const WORK_TYPES = new Map<string, string>([
  ['DEICING_MANUAL', 'Скользко, лёд не посыпан'],
  ['SNOW_MANUAL', 'Не убран снег на дорожке или у входа'],
  ['BIN_EMPTYING', 'Переполненная урна'],
  ['LAWN_LITTER', 'Мусор на газоне'],
  ['METAL_CUTTING', 'Нужно срезать торчащую арматуру или трубу'],
  ['PLAYGROUND_MAINTENANCE', 'Не убрана площадка или сломано оборудование'],
  ['UNPAVED_LITTER', 'Мусор на участке без асфальта и плитки'],
  ['SWEEPING', 'Мусор и песок на дорожках'],
  ['BIN_WASHING', 'Грязная урна'],
  ['LAWN_RAKING', 'На газоне не убраны листья и сухая трава'],
  ['GREEN_CLEANING', 'Не убрана зелёная зона или газон'],
  ['GRASS_MOWING', 'Трава не скошена или не убрана после покоса'],
  ['PAVING_WASHING', 'Грязная плитка или брусчатка'],
  ['SNOW_MECHANICAL', 'Не убран снег на проезде или большой площадке'],
  ['SNOW_REMOVAL', 'Не вывезены кучи снега'],
]);

export function citizenWorkOption(work: {code: string; name: string}) {
  return {value: work.code, label: WORK_TYPES.get(work.code) || work.name};
}
