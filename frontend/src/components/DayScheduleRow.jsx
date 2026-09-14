import React from 'react';
import { useLocale } from '../i18n/LocaleContext';

export function DayScheduleRow({ activeDays = [], todayIndex = 0 }) {
  const { t, locale } = useLocale();
  const dayKeys = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const displayIndexes = locale === 'ar' ? [5, 6, 0, 1, 2, 3, 4] : [0, 1, 2, 3, 4, 5, 6];
  return (
    <div className="schedule-row">
      <div className="schedule-row-label">{t('weeklyDuty')}</div>
      <div className="days-cells">
        {displayIndexes.map((dayIndex) => {
          const day = dayKeys[dayIndex];
          const isActive = activeDays.includes(dayIndex);
          const isToday = dayIndex === todayIndex;
          let cellClass = 'day-cell';
          if (isActive) cellClass += ' active-duty';
          if (isToday) cellClass += ' is-today';

          return (
            <div
              key={dayIndex}
              className={cellClass}
              title={`${t(day)}: ${isActive ? t('onDuty') : t('standby')}${isToday ? ` (${t('today')})` : ''}`}
            >
              {locale === 'ar' ? t(day).slice(0, 2) : t(day).slice(0, 1)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
